# agent-sync Service

A thin Rust service for SSE streaming and log fetching in agent sessions.

## What It Does

```
POST /sync  → Kafka (agent_events topic)
GET /sync   → ClickHouse (replay) + Kafka (live) → SSE
GET /logs   → ClickHouse → JSON
```

ClickHouse ingestion happens via existing Kafka MV - this service only reads from ClickHouse.

## URL Routing

Same path as Django. Ingress routes these endpoints to agent-sync:

```
/api/projects/{id}/tasks/{task_id}/runs/{run_id}/sync   → agent-sync
/api/projects/{id}/tasks/{task_id}/runs/{run_id}/logs   → agent-sync
/api/projects/{id}/tasks/{task_id}/runs/{run_id}/...    → Django (heartbeat, etc)
```

## Endpoints

### GET /logs

Fetch logs as JSON. For viewing completed tasks, export, programmatic access.

```
GET /runs/{run_id}/logs
GET /runs/{run_id}/logs?after=123        # pagination
GET /runs/{run_id}/logs?limit=1000       # limit results
```

Response:
```json
[
  {"sequence": 1, "timestamp": "...", "entry_type": "...", "entry": {...}},
  {"sequence": 2, "timestamp": "...", "entry_type": "...", "entry": {...}}
]
```

### GET /sync

SSE stream. Replays from ClickHouse, then streams live from Kafka.

```
GET /runs/{run_id}/sync
GET /runs/{run_id}/sync  (with Last-Event-ID: 123 header)
```

Response:
```
id: 124
data: {"entry_type": "...", "entry": {...}}

id: 125
data: {"entry_type": "...", "entry": {...}}

: keepalive
```

### POST /sync

Send messages. Both agent server and clients use this.

```
POST /runs/{run_id}/sync
Content-Type: application/json

{"jsonrpc": "2.0", "method": "...", "params": {...}}
```

Response: `202 Accepted`

## Who Uses What

| Actor | POST /sync | GET /sync | GET /logs |
|-------|------------|-----------|-----------|
| Agent server | Tool outputs, responses | User messages, cancel | - |
| Twig client | User messages, cancel | Agent outputs | View history |
| Mobile client | User messages | Agent outputs | View history |
| Slack client | User messages | Agent outputs | - |

All traffic is symmetrical through Kafka - everyone posts, everyone subscribes.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        agent-sync                             │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ AuthService │  │ ClickHouse  │  │    KafkaProducer    │  │
│  │  (cached)   │  │  (read)     │  │                     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│         │         ┌──────┴──────┐              │             │
│         │         │             │              │             │
│         │    GET /logs    GET /sync      POST /sync          │
│         │         │             │              │             │
│         │         │      ┌──────┴──────┐       │             │
│         │         │      │   Kafka     │       │             │
│         │         │      │  Consumer   │       │             │
│         │         │      │  (1/pod)    │       │             │
│         │         │      └──────┬──────┘       │             │
│         │         │             │              │             │
│         │         │      ┌──────┴──────┐       │             │
│         │         │      │  Fanout     │       │             │
│         │         │      │  Router     │       │             │
│         │         │      └──────┬──────┘       │             │
│         │         │             │              │             │
│         │         ▼             ▼              │             │
│         │       JSON          SSE              │             │
└─────────┴───────────────────────┴──────────────┴─────────────┘
                                  │              │
                           ClickHouse         Kafka
                           (agent_logs)    (agent_events)
```

## Core Traits

```rust
#[async_trait]
pub trait AuthService: Send + Sync {
    async fn authenticate(&self, token: &str) -> Result<AuthContext, AuthError>;
}

#[async_trait]
pub trait LogStore: Send + Sync {
    async fn get_logs(&self, run_id: &Uuid, after: Option<u64>, limit: Option<u32>)
        -> Result<Vec<AgentEvent>>;
}

#[async_trait]
pub trait EventPublisher: Send + Sync {
    async fn publish(&self, event: &AgentEvent) -> Result<()>;
}

pub trait EventRouter: Send + Sync {
    fn subscribe(&self, run_id: &str) -> Receiver<AgentEvent>;
    fn unsubscribe(&self, run_id: &str, rx: &Receiver<AgentEvent>);
    fn has_subscribers(&self, run_id: &str) -> bool;
}
```

## Auth (OAuth only, in-memory cache)

```rust
pub struct CachedAuthService {
    cache: RwLock<LruCache<String, CachedEntry>>,
    postgres: PgPool,
    cache_ttl: Duration,
}

impl CachedAuthService {
    async fn authenticate(&self, token: &str) -> Result<AuthContext, AuthError> {
        if !token.starts_with("pha_") {
            return Err(AuthError::InvalidToken);
        }

        let token_hash = sha256_hex(token);

        // Check cache
        if let Some(entry) = self.cache.read().get(&token_hash) {
            if entry.expires_at > Instant::now() {
                return entry.user.clone().ok_or(AuthError::InvalidToken);
            }
        }

        // Query Postgres
        let user = self.lookup_oauth_token(&token_hash).await?;

        // Cache result
        self.cache.write().put(token_hash, CachedEntry {
            user: Some(user.clone()),
            expires_at: Instant::now() + self.cache_ttl,
        });

        Ok(user)
    }

    async fn lookup_oauth_token(&self, token_hash: &str) -> Result<AuthContext, AuthError> {
        let row = sqlx::query!(r#"
            SELECT oat.user_id, oat.expires, u.current_team_id
            FROM posthog_oauthaccesstoken oat
            JOIN posthog_user u ON oat.user_id = u.id
            WHERE oat.token_checksum = $1 AND u.is_active = true
        "#, token_hash)
        .fetch_optional(&self.postgres)
        .await?
        .ok_or(AuthError::InvalidToken)?;

        if let Some(expires) = row.expires {
            if expires < Utc::now() {
                return Err(AuthError::TokenExpired);
            }
        }

        Ok(AuthContext {
            user_id: row.user_id,
            team_id: row.current_team_id,
        })
    }
}
```

## ClickHouse Log Store

```rust
pub struct ClickHouseLogStore {
    client: clickhouse::Client,
}

#[async_trait]
impl LogStore for ClickHouseLogStore {
    async fn get_logs(
        &self,
        run_id: &Uuid,
        after: Option<u64>,
        limit: Option<u32>
    ) -> Result<Vec<AgentEvent>> {
        let after_seq = after.unwrap_or(0);
        let limit = limit.unwrap_or(10000);

        self.client.query(r#"
            SELECT sequence, timestamp, entry_type, entry
            FROM agent_logs
            WHERE run_id = ?
              AND sequence > ?
            ORDER BY sequence ASC
            LIMIT ?
        "#)
        .bind(run_id)
        .bind(after_seq)
        .bind(limit)
        .fetch_all()
        .await
    }
}
```

## Handlers

### GET /logs

```rust
#[derive(Deserialize)]
pub struct LogsQuery {
    after: Option<u64>,
    limit: Option<u32>,
}

pub async fn get_logs(
    State(state): State<AppState>,
    Path((project_id, task_id, run_id)): Path<(i64, Uuid, Uuid)>,
    Query(params): Query<LogsQuery>,
    Extension(auth): Extension<AuthContext>,
) -> Result<Json<Vec<AgentEvent>>, AppError> {
    let events = state.log_store
        .get_logs(&run_id, params.after, params.limit)
        .await?;

    Ok(Json(events))
}
```

### GET /sync

```rust
pub async fn get_sync(
    State(state): State<AppState>,
    Path((project_id, task_id, run_id)): Path<(i64, Uuid, Uuid)>,
    headers: HeaderMap,
    Extension(auth): Extension<AuthContext>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let last_event_id: Option<u64> = headers
        .get("Last-Event-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse().ok());

    let run_id_str = run_id.to_string();
    let log_store = state.log_store.clone();
    let router = state.router.clone();

    let stream = async_stream::stream! {
        // 1. Replay from ClickHouse
        if let Ok(events) = log_store.get_logs(&run_id, last_event_id, None).await {
            for event in events {
                yield Ok(Event::default()
                    .id(event.sequence.to_string())
                    .data(serde_json::to_string(&event.entry).unwrap_or_default()));
            }
        }

        // 2. Subscribe to live events from Kafka
        let mut rx = router.subscribe(&run_id_str);

        loop {
            tokio::select! {
                result = rx.recv() => {
                    match result {
                        Ok(event) => {
                            yield Ok(Event::default()
                                .id(event.sequence.to_string())
                                .data(serde_json::to_string(&event.entry).unwrap_or_default()));
                        }
                        Err(_) => break,
                    }
                }
                _ = tokio::time::sleep(Duration::from_secs(30)) => {
                    yield Ok(Event::default().comment("keepalive"));
                }
            }
        }
    };

    Sse::new(stream)
}
```

### POST /sync

```rust
pub async fn post_sync(
    State(state): State<AppState>,
    Path((project_id, task_id, run_id)): Path<(i64, Uuid, Uuid)>,
    Extension(auth): Extension<AuthContext>,
    Json(message): Json<Value>,
) -> Result<StatusCode, AppError> {
    let event = AgentEvent {
        team_id: auth.team_id,
        task_id,
        run_id,
        sequence: Utc::now().timestamp_micros() as u64,
        timestamp: Utc::now(),
        entry_type: extract_entry_type(&message),
        entry: message,
    };

    state.publisher.publish(&event).await?;

    Ok(StatusCode::ACCEPTED)
}
```

## Fanout Router

```rust
pub struct FanoutRouter {
    subscriptions: RwLock<HashMap<String, Vec<Sender<AgentEvent>>>>,
}

impl FanoutRouter {
    pub fn new() -> Self {
        Self {
            subscriptions: RwLock::new(HashMap::new()),
        }
    }

    pub fn subscribe(&self, run_id: &str) -> Receiver<AgentEvent> {
        let (tx, rx) = mpsc::channel(1000);
        self.subscriptions.write()
            .entry(run_id.to_string())
            .or_default()
            .push(tx);
        rx
    }

    pub fn has_subscribers(&self, run_id: &str) -> bool {
        self.subscriptions.read()
            .get(run_id)
            .map(|s| !s.is_empty())
            .unwrap_or(false)
    }

    pub async fn route(&self, event: AgentEvent) {
        let run_id = event.run_id.to_string();
        if let Some(senders) = self.subscriptions.read().get(&run_id) {
            for tx in senders {
                let _ = tx.try_send(event.clone());
            }
        }
    }

    pub fn cleanup_closed(&self, run_id: &str) {
        let mut subs = self.subscriptions.write();
        if let Some(senders) = subs.get_mut(run_id) {
            senders.retain(|tx| !tx.is_closed());
            if senders.is_empty() {
                subs.remove(run_id);
            }
        }
    }
}
```

## Kafka Consumer

```rust
pub async fn run_consumer(
    consumer: StreamConsumer,
    router: Arc<FanoutRouter>,
    shutdown: CancellationToken,
) {
    loop {
        tokio::select! {
            _ = shutdown.cancelled() => break,
            result = consumer.recv() => {
                let Ok(msg) = result else {
                    tokio::time::sleep(Duration::from_millis(100)).await;
                    continue;
                };

                let Some(key) = msg.key().and_then(|k| str::from_utf8(k).ok()) else {
                    continue;
                };

                // Key format: {task_id}:{run_id}
                let run_id = key.split(':').nth(1).unwrap_or("");

                // Skip if no subscribers
                if !router.has_subscribers(run_id) {
                    continue;
                }

                if let Ok(event) = serde_json::from_slice(msg.payload().unwrap_or_default()) {
                    router.route(event).await;
                }
            }
        }
    }
}
```

## App State & Router

```rust
pub struct AppState {
    pub auth: Arc<dyn AuthService>,
    pub log_store: Arc<dyn LogStore>,
    pub publisher: Arc<dyn EventPublisher>,
    pub router: Arc<FanoutRouter>,
}

pub fn create_router(state: AppState) -> Router {
    Router::new()
        .route(
            "/api/projects/:project_id/tasks/:task_id/runs/:run_id/sync",
            get(get_sync).post(post_sync)
        )
        .route(
            "/api/projects/:project_id/tasks/:task_id/runs/:run_id/logs",
            get(get_logs)
        )
        .route("/health", get(health))
        .route("/ready", get(ready))
        .layer(from_fn_with_state(state.clone(), auth_middleware))
        .with_state(state)
}
```

## Project Structure

```
rust/agent-sync/
├── Cargo.toml
├── src/
│   ├── main.rs
│   ├── config.rs
│   ├── app.rs                  # Router, AppState
│   ├── auth/
│   │   ├── mod.rs
│   │   ├── service.rs          # CachedAuthService
│   │   └── middleware.rs
│   ├── store/
│   │   ├── mod.rs
│   │   └── clickhouse.rs       # ClickHouseLogStore
│   ├── kafka/
│   │   ├── mod.rs
│   │   ├── producer.rs
│   │   └── consumer.rs
│   ├── streaming/
│   │   ├── mod.rs
│   │   └── fanout.rs
│   ├── handlers/
│   │   ├── mod.rs
│   │   ├── logs.rs
│   │   ├── sync_get.rs
│   │   └── sync_post.rs
│   └── error.rs
└── tests/
    ├── auth_test.rs
    ├── logs_test.rs
    └── fanout_test.rs
```

## Configuration

```rust
#[derive(Envconfig)]
pub struct Config {
    #[envconfig(default = "::")]
    pub host: String,

    #[envconfig(default = "8080")]
    pub port: u16,

    #[envconfig(nested)]
    pub kafka: KafkaConfig,

    #[envconfig(default = "agent_events")]
    pub kafka_topic: String,

    pub database_url: String,

    #[envconfig(default = "4")]
    pub max_pg_connections: u32,

    pub clickhouse_url: String,

    #[envconfig(default = "default")]
    pub clickhouse_database: String,

    #[envconfig(default = "300")]
    pub auth_cache_ttl_secs: u64,

    #[envconfig(default = "10000")]
    pub auth_cache_max_size: usize,

    #[envconfig(default = "30")]
    pub sse_keepalive_secs: u64,

    #[envconfig(default = "10000")]
    pub max_logs_limit: u32,
}
```

## Deployment

Add to `charts/apps/agent-sync/`:

```yaml
replicaCount: 3

image:
  repository: posthog/agent-sync
  tag: latest

resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "1Gi"
    cpu: "1000m"

env:
  - name: KAFKA_HOSTS
    valueFrom:
      secretKeyRef:
        name: kafka-secrets
        key: hosts
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: postgres-secrets
        key: url
  - name: CLICKHOUSE_URL
    valueFrom:
      secretKeyRef:
        name: clickhouse-secrets
        key: url
```

Ingress routing:
```yaml
- path: /api/projects/*/tasks/*/runs/*/sync
  backend:
    service:
      name: agent-sync
      port: 8080
- path: /api/projects/*/tasks/*/runs/*/logs
  backend:
    service:
      name: agent-sync
      port: 8080
```

## Testing

```rust
#[cfg(test)]
mod tests {
    struct MockAuthService(AuthContext);

    #[async_trait]
    impl AuthService for MockAuthService {
        async fn authenticate(&self, _: &str) -> Result<AuthContext, AuthError> {
            Ok(self.0.clone())
        }
    }

    struct MockLogStore {
        events: Vec<AgentEvent>,
    }

    #[async_trait]
    impl LogStore for MockLogStore {
        async fn get_logs(&self, _: &Uuid, after: Option<u64>, limit: Option<u32>)
            -> Result<Vec<AgentEvent>>
        {
            let after = after.unwrap_or(0);
            Ok(self.events.iter()
                .filter(|e| e.sequence > after)
                .take(limit.unwrap_or(10000) as usize)
                .cloned()
                .collect())
        }
    }

    #[tokio::test]
    async fn test_get_logs_returns_json() {
        let events = vec![
            AgentEvent { sequence: 1, ..Default::default() },
            AgentEvent { sequence: 2, ..Default::default() },
        ];

        let state = AppState {
            auth: Arc::new(MockAuthService(AuthContext::test())),
            log_store: Arc::new(MockLogStore { events }),
            publisher: Arc::new(MockEventPublisher::new()),
            router: Arc::new(FanoutRouter::new()),
        };

        let response = get_logs(
            State(state),
            Path((1, Uuid::new_v4(), Uuid::new_v4())),
            Query(LogsQuery { after: None, limit: None }),
            Extension(AuthContext::test()),
        ).await.unwrap();

        assert_eq!(response.0.len(), 2);
    }

    #[tokio::test]
    async fn test_get_logs_with_after_filter() {
        let events = vec![
            AgentEvent { sequence: 1, ..Default::default() },
            AgentEvent { sequence: 2, ..Default::default() },
            AgentEvent { sequence: 3, ..Default::default() },
        ];

        let state = AppState {
            auth: Arc::new(MockAuthService(AuthContext::test())),
            log_store: Arc::new(MockLogStore { events }),
            publisher: Arc::new(MockEventPublisher::new()),
            router: Arc::new(FanoutRouter::new()),
        };

        let response = get_logs(
            State(state),
            Path((1, Uuid::new_v4(), Uuid::new_v4())),
            Query(LogsQuery { after: Some(1), limit: None }),
            Extension(AuthContext::test()),
        ).await.unwrap();

        assert_eq!(response.0.len(), 2);
        assert_eq!(response.0[0].sequence, 2);
    }
}
```

## Implementation Order

1. **Scaffold** (0.5 day) - crate, config, health
2. **Auth** (1 day) - OAuth lookup + in-memory cache
3. **ClickHouse store** (0.5 day) - log queries
4. **GET /logs handler** (0.5 day)
5. **Kafka producer + POST /sync** (0.5 day)
6. **Fanout + consumer** (1 day)
7. **GET /sync SSE** (0.5 day)
8. **Tests** (1 day)
9. **Deployment** (0.5 day)

**Total: ~6 days**
