# Pod Rebalancer - Enhanced Implementation Plan with Go Best Practices

## Implementation Status

| Phase | Commit | Status | Branch | Commit Hash | Date |
|-------|--------|--------|---------|-------------|------|
| 1 | 1. Project Bootstrap | ✅ **COMPLETED** | `feat/pod-rebalancer-bootstrap` | `242747c31d` | 2025-01-13 |
| 1 | 2. Environment Config & Logging | ⏳ **NEXT** | `feat/config-and-logging` | - | - |
| 1 | 3. Prometheus Client & Metrics | 📋 **PLANNED** | `feat/prometheus-client` | - | - |
| 2 | 4. Complete Metrics Fetchers | 📋 **PLANNED** | `feat/all-metrics-fetchers` | - | - |
| 2 | 5. Pod State & Decision Engine | 📋 **PLANNED** | `feat/podstate-and-decision` | - | - |
| 3 | 6. Kubernetes Pod Management | 📋 **PLANNED** | `feat/kubernetes-manager` | - | - |
| 3 | 7. Main Application Integration | 📋 **PLANNED** | `feat/main-application` | - | - |
| 3 | 8. Docker & Documentation | 📋 **PLANNED** | `feat/deployment-and-docs` | - | - |

### Current State
- **Active Branch**: `pl/ingestion/ingestion_pod_rebalancer`
- **Last Completed**: Commit 1 - Project Bootstrap with Go Best Practices
- **Next Target**: Commit 2 - Environment Configuration & Basic Logging
- **Project Location**: `/Users/posthog/Projects/src/PostHog/posthog/infra-scripts/pod-rebalancer/`

### Resume Instructions
To continue development from any point:

```bash
# Navigate to project
cd /Users/posthog/Projects/src/PostHog/posthog/infra-scripts/pod-rebalancer/

# Check current status
git status
git log --oneline -5

# Set up development environment (if not already done)
./scripts/install-tools.sh
task dev-setup

# Verify everything works
task check
task build

# Continue with next commit (see detailed plan below)
```

## Commit-by-Commit Strategy (8 Total Commits)

### Phase 1: Foundation (Commits 1-3)

#### Commit 1: Project Bootstrap with Go Best Practices ✅ **COMPLETED**
**Branch**: `feat/pod-rebalancer-bootstrap`
**Status**: ✅ Completed on 2025-01-13 (commit `242747c31d`)
**Files**: 
- `pod-rebalancer/go.mod`
- `pod-rebalancer/go.sum` 
- `pod-rebalancer/Taskfile.yml`
- `pod-rebalancer/.golangci.yml`
- `pod-rebalancer/.envrc`
- `pod-rebalancer/tools.go`
- `pod-rebalancer/README.md`
- `pod-rebalancer/.gitignore`
- `pod-rebalancer/cmd/rebalancer/main.go` (skeleton)
- `pod-rebalancer/scripts/install-tools.sh`
- `pod-rebalancer/docs/development.md`

**Tasks**:
1. Initialize Go module with official dependencies:
   ```bash
   go mod init github.com/posthog/pod-rebalancer
   go get github.com/prometheus/client_golang/api/prometheus/v1
   go get github.com/prometheus/client_golang/prometheus
   go get github.com/prometheus/common/model
   go get k8s.io/client-go@latest
   go get k8s.io/api/core/v1
   go get go.uber.org/zap
   go get github.com/stretchr/testify
   ```

2. Create enhanced project structure with best practices:
   ```
   pod-rebalancer/
   ├── .envrc                       # Development environment variables
   ├── .golangci.yml               # Linter configuration
   ├── tools.go                    # Tool dependencies
   ├── Taskfile.yml                # Enhanced task runner
   ├── scripts/
   │   └── install-tools.sh        # Development setup
   ├── docs/
   │   └── development.md          # Development guide
   ├── examples/
   │   └── docker-compose.yml      # Local testing setup
   ```

3. Create comprehensive Taskfile.yml with Go best practices:
   ```yaml
   version: '3'
   
   tasks:
     tools:
       desc: Install development tools
       cmds:
         - go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
         - go install golang.org/x/vuln/cmd/govulncheck@latest
         - go install golang.org/x/tools/cmd/goimports@latest
   
     deps:
       desc: Download and tidy dependencies
       cmds:
         - go mod download
         - go mod tidy
   
     fmt:
       desc: Format code and organize imports
       cmds:
         - gofmt -s -w .
         - goimports -w .
         - test -z "$(gofmt -l .)"
   
     vet:
       desc: Run go vet
       cmds:
         - go vet ./...
   
     lint:
       desc: Run golangci-lint
       cmds:
         - golangci-lint run
   
     test:
       desc: Run tests with race detection
       cmds:
         - go test -v -race ./...
   
     test-coverage:
       desc: Run tests with coverage report
       cmds:
         - go test -v -race -coverprofile=coverage.out ./...
         - go tool cover -html=coverage.out -o coverage.html
         - go tool cover -func=coverage.out
   
     security:
       desc: Check for security vulnerabilities
       cmds:
         - govulncheck ./...
   
     build:
       desc: Build optimized binary
       cmds:
         - go build -ldflags="-s -w" -o bin/rebalancer ./cmd/rebalancer
   
     docker:
       desc: Build Docker image
       cmds:
         - docker build -t pod-rebalancer .
   
     check:
       desc: Run all quality checks
       deps: [fmt, vet, lint, test, security]
   
     clean:
       desc: Clean build artifacts
       cmds:
         - rm -rf bin/
         - rm -f coverage.out coverage.html
   
     dev-setup:
       desc: Set up development environment
       deps: [tools, deps]
   ```

4. Create `.golangci.yml` with strict linting rules
5. Create `.envrc` for development environment variables
6. Create `tools.go` for tool dependency management
7. Create development documentation and examples

**Acceptance Criteria**:
- `task dev-setup` installs all development tools
- `task check` passes all quality checks
- `task build` produces optimized binary
- Development environment loads automatically with direnv
- All Go best practices are configured and working

#### Commit 2: Environment Configuration & Basic Logging ⏳ **NEXT**
**Branch**: `feat/config-and-logging`
**Status**: ⏳ Ready to implement
**Files**:
- `pkg/config/env.go`
- `pkg/config/env_test.go`
- `pkg/logging/logger.go`
- `pkg/logging/metrics.go`
- `pkg/logging/logging_test.go`

**Tasks**:
1. Define Config struct with all environment variables
2. Implement environment variable parsing with defaults
3. Add configuration validation for required fields
4. Create simple structured logger with zap
5. Add basic Prometheus metrics using official client (counters, gauges)

**Environment Variables**:
```bash
PROMETHEUS_ENDPOINT=http://victoriametrics:8428
PROMETHEUS_TIMEOUT=30s
KUBE_NAMESPACE=default
KUBE_LABEL_SELECTOR=app=consumer
STRATEGY=balanced
CPU_VARIANCE_THRESHOLD=0.3
LAG_VARIANCE_THRESHOLD=0.5
MAX_PODS_TO_DELETE=2
MIN_PODS_REQUIRED=3
DRY_RUN=false
LOG_LEVEL=info
```

**Acceptance Criteria**:
- Environment variables load with proper defaults
- Configuration validation catches invalid values
- Structured JSON logging works
- Basic Prometheus metrics are defined

#### Commit 3: Prometheus Client & Basic Metrics Fetching
**Branch**: `feat/prometheus-client`
**Files**:
- `pkg/prometheus/client.go`
- `pkg/prometheus/client_test.go`
- `pkg/metrics/cpu.go`
- `pkg/metrics/metrics_test.go`

**Tasks**:
1. Implement Prometheus client using official Go client library
2. Add query execution with timeout and error handling
3. Create CPUMetricsFetcher as first concrete implementation
4. Add response parsing for Prometheus vector/matrix types
5. Test with mocked HTTP responses

**Prometheus Client Features**:
- Uses official github.com/prometheus/client_golang/api
- Query execution with context cancellation using v1.API
- Response parsing (model.Vector and model.Matrix types)
- Basic error handling for network/API errors

**CPU Metrics Query**:
```promql
rate(container_cpu_usage_seconds_total{pod=~"consumer-.*"}[5m])
```

**Acceptance Criteria**:
- Prometheus client successfully queries endpoints
- CPU metrics fetcher returns pod->usage map
- Error handling for network failures
- Unit tests with mocked HTTP client

### Phase 2: Core Metrics & State Management (Commits 4-5)

#### Commit 4: Complete Metrics Fetchers
**Branch**: `feat/all-metrics-fetchers`
**Files**:
- `pkg/metrics/kafka.go`
- `pkg/metrics/memory.go`
- `pkg/metrics/metrics_test.go` (expanded)
- `internal/testutil/mocks.go`

**Tasks**:
1. Implement KafkaMetricsFetcher for lag and consumption rate
2. Implement MemoryMetricsFetcher for memory usage
3. Add parallel fetching capability for all metrics
4. Create comprehensive test mocks for all metric types
5. Add error handling for missing/invalid metrics

**Key Queries**:
```promql
# Kafka consumer lag
kafka_consumer_lag_sum{pod=~"consumer-.*"}

# Message consumption rate  
rate(kafka_consumer_messages_consumed_total{pod=~"consumer-.*"}[5m])

# Memory usage per pod
container_memory_working_set_bytes{pod=~"consumer-.*"}
```

**Acceptance Criteria**:
- All three metric fetchers work independently
- Parallel fetching reduces total query time
- Handles missing metrics gracefully
- Comprehensive unit tests with realistic data

### Phase 2: Core Logic (Commits 5-8)

#### Commit 5: Pod State Aggregation & Decision Engine
**Branch**: `feat/podstate-and-decision`
**Files**:
- `pkg/podstate/aggregator.go`
- `pkg/podstate/aggregator_test.go`
- `pkg/decision/engine.go`
- `pkg/decision/outliers.go`
- `pkg/decision/decision_test.go`

**Tasks**:
1. Implement PodState aggregator that combines all metrics
2. Create composite scoring algorithm (weighted CPU, lag, memory)
3. Implement statistical analysis (variance, std dev, percentiles)
4. Add decision engine with threshold-based rebalancing logic
5. Implement rotate outliers strategy (most busy + least busy)

**Composite Scoring**:
```go
// Weight different metrics for composite score
func calculateCompositeScore(cpu, lag, memory float64) float64 {
    return (cpu * 0.4) + (normalizedLag * 0.4) + (memory * 0.2)
}
```

**Strategy**:
- Always rotates outliers: Deletes the pod with the highest composite score (most busy) and the pod with the lowest composite score (least busy)

**Acceptance Criteria**:
- Aggregator combines metrics from all fetchers correctly
- Decision engine calculates proper statistics
- Strategy correctly selects most busy and least busy pods
- Handles edge cases (too few pods, equal load)

### Phase 3: Kubernetes Integration & Main Application (Commits 6-8)

#### Commit 6: Kubernetes Pod Management
**Branch**: `feat/kubernetes-manager`
**Files**:
- `pkg/kubernetes/manager.go`
- `pkg/kubernetes/manager_test.go`

**Tasks**:
1. Implement Kubernetes client using official k8s.io/client-go
2. Add basic safety validation (minimum pod count)
3. Implement pod deletion with dry-run support using client.CoreV1().Pods()
4. Add structured logging for all operations

**Manager Features**:
```go
type Manager struct {
    client    kubernetes.Interface
    namespace string
    dryRun    bool
    minPods   int
}

func (m *Manager) DeletePods(ctx context.Context, podNames []string) (*DeletionResult, error) {
    // 1. Validate minimum pod count would be maintained
    // 2. For each pod: either delete (real) or log (dry-run)
    // 3. Return detailed results
}
```

**Acceptance Criteria**:
- Successfully deletes pods using official k8s.io/client-go
- Respects minimum pod count safety check
- Dry-run mode logs actions without deleting
- Uses kubernetes.Interface for easy mocking in tests

#### Commit 7: Main Application Integration
**Branch**: `feat/main-application`
**Files**:
- `cmd/rebalancer/main.go` (complete implementation)
- Integration between all packages

**Tasks**:
1. Implement complete main.go with all components
2. Wire together all packages in the correct order
3. Add proper error handling and exit codes
4. Implement structured logging throughout execution
5. Add basic performance measurement

**Main Application Flow**:
```go
func main() {
    ctx := context.Background()
    
    // 1. Load configuration and create logger
    config := config.LoadFromEnv()
    logger := logging.New(config.LogLevel)
    
    // 2. Create Prometheus client
    promClient := prometheus.NewHTTPClient(config.PrometheusEndpoint, config.Timeout)
    
    // 3. Create and wire all components
    aggregator := podstate.NewAggregator(
        metrics.NewCPUFetcher(promClient),
        metrics.NewKafkaFetcher(promClient),
        metrics.NewMemoryFetcher(promClient),
    )
    
    engine := decision.NewEngine(config.Thresholds)
    k8sManager := kubernetes.NewManager(config.Namespace, config.DryRun, config.MinPods)
    
    // 4. Execute the complete workflow
    // 5. Log results and exit with appropriate code
}
```

**Acceptance Criteria**:
- Complete application runs end-to-end
- All error cases handled with proper exit codes  
- Structured logging shows complete execution flow
- Performance is measured and logged

#### Commit 8: Docker & Documentation
**Branch**: `feat/deployment-and-docs`
**Files**:
- `deploy/docker/Dockerfile`
- `README.md` (complete)
- `test/integration_test.go`

**Tasks**:
1. Create optimized multi-stage Dockerfile
2. Write comprehensive README with usage examples
3. Add basic integration test with test containers
4. Document all environment variables and configuration
5. Add Docker build and test automation

**Docker Features**:
- Multi-stage build for minimal image size
- Non-root user for security
- Alpine base for small footprint
- Uses official Go and Alpine images

**Acceptance Criteria**:
- Docker image builds and runs successfully
- README covers installation, configuration, and usage
- Integration test validates end-to-end functionality
- All dependencies use official/popular packages

## Testing Strategy

### Unit Testing (Each Commit)
- **prometheus**: HTTP client with mocked responses
- **metrics**: Individual fetchers with known test data
- **podstate**: Aggregation logic with predictable inputs  
- **decision**: Statistical analysis with synthetic datasets
- **kubernetes**: Pod operations with mocked K8s client
- **config**: Environment parsing with various inputs

### Integration Testing (Commit 8)
- End-to-end test with test containers (Prometheus + K8s)
- Network failure scenarios
- Large dataset performance (1000+ pods)
- Concurrent execution safety

### Enhanced Acceptance Testing with Go Best Practices
Each commit must:
- Pass `task check` (includes fmt, vet, lint, test, security)
- Achieve >90% test coverage with `task test-coverage`
- Build successfully with `task build`
- Pass security scan with `govulncheck`
- Follow Go code formatting standards with `goimports`
- All tools managed through `tools.go` pattern

## Deployment Strategy

### Development
```bash
# Run locally with dry-run
export DRY_RUN=true
export PROMETHEUS_ENDPOINT=http://localhost:9090
./pod-rebalancer
```

### Production
```bash
# Deploy to Kubernetes (manifests in separate repo)
kubectl apply -f ../k8s-manifests/pod-rebalancer/

# Monitor execution
kubectl logs -l job-name=pod-rebalancer-<timestamp>
```

## Monitoring & Alerting

### Key Metrics
- `rebalancer_executions_total{status="success|error"}`
- `rebalancer_pods_analyzed_total`
- `rebalancer_pods_deleted_total{type="most_busy|least_busy"}`
- `rebalancer_execution_duration_seconds`
- `rebalancer_load_variance_current`

### Critical Alerts
- Consecutive execution failures (3+)
- No pods found matching selector
- Excessive pod deletions (>50% of pods)
- High load variance persisting (>threshold for 30+ minutes)

This simplified plan delivers a production-ready stateless application in 8 focused commits, with each commit building working functionality incrementally.

---

## Progress Tracking & Maintenance

### How to Update This Document

When completing each commit, update the status table at the top:

1. **Change status** from ⏳ **NEXT** to ✅ **COMPLETED**
2. **Add commit hash** from `git log --oneline -1`  
3. **Add completion date**
4. **Update "Current State" section**
5. **Mark next commit** as ⏳ **NEXT**

### Example Status Update
```markdown
| 1 | 2. Environment Config & Logging | ✅ **COMPLETED** | `feat/config-and-logging` | `abc123def` | 2025-01-13 |
| 1 | 3. Prometheus Client & Metrics | ⏳ **NEXT** | `feat/prometheus-client` | - | - |
```

### Quick Commands for Status Updates
```bash
# Get latest commit hash for updating table
git log --oneline -1

# Get current date in ISO format
date +%Y-%m-%d

# Check current branch
git branch --show-current
```

### Status Legend
- ✅ **COMPLETED** - Implementation finished and committed
- ⏳ **NEXT** - Ready to implement (next target)  
- 📋 **PLANNED** - Planned for future implementation
- 🚧 **IN PROGRESS** - Currently being worked on
- ❌ **BLOCKED** - Blocked by dependencies or issues

### Resuming Development
Anyone can resume development at any time by:
1. Checking the status table for the next commit
2. Following the resume instructions at the top
3. Implementing the detailed commit plan below
4. Updating the status table when complete

This document serves as the single source of truth for implementation progress.

