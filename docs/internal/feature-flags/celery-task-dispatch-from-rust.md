# Dispatching Celery tasks from Rust

The `common-redis` crate provides a `celery` module that lets any Rust service dispatch tasks to Django's Celery workers without needing a Python process or the Celery client library.

## How it works

Celery uses Redis as its message broker. Tasks are JSON messages sitting in a Redis list (the `celery` key by default). Workers consume them with `BRPOP`.

The Rust function builds a message that conforms to the [Celery v2 message protocol](https://docs.celeryq.dev/en/stable/internals/protocol.html) and `LPUSH`es it to the queue. From the worker's perspective, it's indistinguishable from a task sent by Python.

```text
Rust service
  │
  │  LPUSH "celery" <json envelope>
  ▼
Redis (broker)
  │
  │  BRPOP "celery"
  ▼
Celery worker (Django)
  │
  │  Deserializes envelope, resolves task name, calls function
  ▼
@shared_task handler
```

## Usage

```rust
use common_redis::celery::send_celery_task;

send_celery_task(
    &redis_client,
    "posthog.tasks.my_module.my_task",
    &serde_json::json!([1, "hello"]),
    &serde_json::json!({"team_id": 42}),
).await?;
```

The task name must be the fully qualified Python path to a `@shared_task` function that Celery's `autodiscover_tasks()` has registered. On the Django side, the task is a normal shared task:

```python
from celery import shared_task

@shared_task(ignore_result=True)
def my_task(x, greeting, team_id=None):
    ...
```

## Message format

The envelope pushed to Redis looks like:

```json
{
  "body": "<base64-encoded JSON: [args, kwargs, embed]>",
  "content-encoding": "utf-8",
  "content-type": "application/json",
  "headers": {
    "lang": "py",
    "task": "posthog.tasks.my_module.my_task",
    "id": "<uuid>",
    "root_id": "<uuid>",
    "parent_id": null,
    "retries": 0,
    "timelimit": [null, null],
    "origin": "posthog-rust",
    "ignore_result": true
  },
  "properties": {
    "correlation_id": "<uuid>",
    "delivery_mode": 2,
    "delivery_info": { "exchange": "", "routing_key": "celery" },
    "priority": 0,
    "body_encoding": "base64",
    "delivery_tag": "<uuid>"
  }
}
```

The `body`, once base64-decoded, is a JSON array: `[args, kwargs, embed]`. The `embed` object (`callbacks`, `errbacks`, `chain`, `chord`) is always null for standalone tasks.

## Code location

- Module: `rust/common/redis/src/celery.rs`
- `build_celery_message()` builds the JSON envelope (pure function, no I/O)
- `send_celery_task()` builds + pushes to Redis via the `Client` trait

## Testing

Tests validate the serialization contract without needing Redis:

```bash
cd rust && cargo test -p common-redis -- celery
```

Since the message format is the contract between Rust and Python, the tests verify the JSON structure matches what Celery expects. Celery's own deserialization is well-tested library code and doesn't need additional coverage on our side.
