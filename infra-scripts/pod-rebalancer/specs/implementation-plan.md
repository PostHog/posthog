# Pod Rebalancer - Enhanced Implementation Plan with Go Best Practices

## Implementation Status

| Phase | Commit | Status | Branch | Commit Hash | Date |
|-------|--------|--------|---------|-------------|------|
| 1 | 1. Project Bootstrap | ✅ **COMPLETED** | `feat/pod-rebalancer-bootstrap` | `242747c31d` | 2025-01-13 |
| 1 | 2. Environment Config & Logging | ✅ **COMPLETED** | `pl/ingestion/ingestion_pod_rebalancer` | `d96c791037` | 2025-01-13 |
| 1 | 3. Prometheus Client & CPU Metrics | ✅ **COMPLETED** | `pl/ingestion/ingestion_pod_rebalancer` | `cffd3b4438` | 2025-01-13 |
| 2 | 4. Pod State & Decision Engine | ✅ **COMPLETED** | `pl/ingestion/ingestion_pod_rebalancer` | `6b1927c61a` | 2025-09-14 |
| 2 | 5. Kubernetes Pod Management | ✅ **COMPLETED** | `pl/ingestion/ingestion_pod_rebalancer` | `16a9038bd9` | 2025-09-14 |
| 3 | 6. Main Application Integration | ✅ **COMPLETED** | `pl/ingestion/ingestion_pod_rebalancer` | `16a9038bd9` | 2025-09-14 |
| 3 | 7. Docker & Documentation | 📋 **PLANNED** | `feat/deployment-and-docs` | - | - |

### Current State
- **Active Branch**: `pl/ingestion/ingestion_pod_rebalancer`
- **Last Completed**: Commit 6 - Main Application Integration (16a9038bd9)
- **Next Target**: Commit 7 - Docker & Documentation
- **Project Location**: `/Users/posthog/Projects/src/PostHog/posthog/infra-scripts/pod-rebalancer/`

### Recent Improvements (2025-01-13)
- **Config Management**: Upgraded to Viper for robust environment variable handling
- **Testing Framework**: Added Ginkgo+Gomega for BDD-style testing alongside traditional Go tests
- **Code Quality**: Simplified configuration loading while maintaining full test coverage
- **Architecture Simplification**: Decided to focus solely on CPU metrics for initial implementation
- **Benefits**: Industry-standard libraries, reduced complexity, better maintainability, focused scope

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
KUBE_NAMESPACE=posthog
KUBE_LABEL_SELECTOR=app=consumer
DEPLOYMENT_NAME=ingestion-consumer
METRICS_TIME_WINDOW=5m
CPU_VARIANCE_THRESHOLD=0.3
MIN_PODS_REQUIRED=3
DRY_RUN=false
LOG_LEVEL=info
```

**Acceptance Criteria**:
- Environment variables load with proper defaults
- Configuration validation catches invalid values
- Structured JSON logging works
- Basic Prometheus metrics are defined

#### Commit 3: Prometheus Client & CPU Metrics ✅ **COMPLETED**
**Branch**: `pl/ingestion/ingestion_pod_rebalancer`
**Status**: ✅ Completed on 2025-01-13 (commit `cffd3b4438`)
**Files**:
- `pkg/prometheus/client.go`
- `pkg/prometheus/client_ginkgo_test.go`
- `pkg/prometheus/prometheus_suite_test.go`
- `pkg/metrics/cpu.go`
- `pkg/metrics/cpu_ginkgo_test.go`
- `pkg/metrics/metrics_suite_test.go`
- `examples/cpu_metrics_example.go`

**Tasks** ✅:
1. ✅ Implement Prometheus client using official Go client library
2. ✅ Add query execution with timeout and error handling
3. ✅ Create CPUMetricsFetcher with per-pod CPU usage, limits, and requests
4. ✅ Add response parsing for Prometheus vector/matrix types
5. ✅ Test with mocked HTTP responses using testify mocks
6. ✅ Migrate all tests to Ginkgo BDD framework
7. ✅ Use PostHog-specific container queries with literal matching

**Prometheus Client Features**:
- Uses custom HTTP client with configurable timeout
- Query execution with context cancellation
- Response parsing (model.Vector and model.Matrix types)
- Health check endpoint validation
- Comprehensive error handling for network/API errors

**CPU Metrics Queries**:
```promql
# Per-pod CPU usage (main query)
sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[5m]))

# CPU limits and requests for resource planning
median(sum(median by (container) (kube_pod_container_resource_limits{resource="cpu", namespace="posthog", container="ingestion-consumer"})))
median(sum(median by (container) (kube_pod_container_resource_requests{resource="cpu", namespace="posthog", container="ingestion-consumer"})))
```

**Acceptance Criteria** ✅:
- ✅ Prometheus client successfully queries endpoints
- ✅ CPU metrics fetcher returns pod->usage map
- ✅ Comprehensive error handling for network failures
- ✅ All tests using Ginkgo BDD framework with testify mocks
- ✅ PostHog-specific queries with literal container matching
- ✅ Configurable time windows and deployment names
- ✅ Tests focus on interface behavior, not struct properties

### Phase 2: Core Logic - CPU-Only Approach (Commits 4-6)

#### Commit 4: Pod State Aggregation & Decision Engine (CPU-Only)
**Branch**: `pl/ingestion/ingestion_pod_rebalancer`
**Files**:
- `pkg/podstate/aggregator.go`
- `pkg/podstate/aggregator_test.go`
- `pkg/decision/engine.go`
- `pkg/decision/engine_test.go`

**Tasks**:
1. Implement PodState aggregator that works with CPU metrics only
2. Create CPU-based scoring algorithm using per-pod CPU usage
3. Implement statistical analysis (variance, std dev, percentiles) for CPU metrics
4. Add decision engine with CPU variance threshold-based rebalancing logic
5. Implement simplified strategy: remove highest and lowest CPU usage pods

**CPU-Only Scoring**:
```go
// Simplified scoring based solely on CPU usage
func calculateCPUScore(cpuUsage float64) float64 {
    return cpuUsage // Direct CPU usage as score
}

// Statistical analysis for CPU variance
func analyzeVariance(cpuUsages map[string]float64) CPUStatistics {
    // Calculate mean, std dev, variance for CPU usage distribution
}
```

**Strategy**:
- Focus exclusively on CPU load balancing
- Remove pod with highest CPU usage (most busy) and lowest CPU usage (least busy)
- Trigger rebalancing when CPU variance exceeds threshold
- Simple, focused approach for initial implementation

**Acceptance Criteria**:
- Aggregator processes CPU metrics correctly
- Decision engine calculates CPU statistics properly
- Strategy correctly identifies highest and lowest CPU usage pods
- Handles edge cases (too few pods, equal load)
- Clean separation of concerns between aggregation and decision logic

#### Commit 5: Kubernetes Pod Management
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

### Phase 3: Application Integration & Deployment (Commits 6-7)

#### Commit 6: Main Application Integration
**Branch**: `feat/main-application`
**Files**:
- `cmd/rebalancer/main.go` (complete implementation)
- Integration between all packages

**Tasks**:
1. Implement complete main.go with CPU-only workflow
2. Wire together all packages in the correct order
3. Add proper error handling and exit codes
4. Implement structured logging throughout execution
5. Add basic performance measurement

**Main Application Flow (CPU-Only)**:
```go
func main() {
    ctx := context.Background()
    
    // 1. Load configuration and create logger
    config := config.LoadFromEnv()
    logger := logging.New(config.LogLevel)
    
    // 2. Create Prometheus client
    promClient := prometheus.NewClient(config.PrometheusEndpoint, config.PrometheusTimeout)
    
    // 3. Create and wire CPU-focused components
    cpuFetcher := metrics.NewCPUMetricsFetcher(promClient, logger, 
        config.KubeNamespace, config.DeploymentName, config.MetricsTimeWindow)
    
    aggregator := podstate.NewAggregator(cpuFetcher, logger)
    engine := decision.NewEngine(config.CPUVarianceThreshold, logger)
    k8sManager := kubernetes.NewManager(config.KubeNamespace, config.DryRun, config.MinPodsRequired)
    
    // 4. Execute the CPU-based rebalancing workflow
    // 5. Log results and exit with appropriate code
}
```

**Acceptance Criteria**:
- Complete CPU-based application runs end-to-end
- All error cases handled with proper exit codes  
- Structured logging shows complete execution flow
- Performance is measured and logged
- Focused on CPU metrics only

#### Commit 7: Docker & Documentation
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

## Monitoring & Alerting (CPU-Only Focus)

### Key Metrics
- `rebalancer_executions_total{status="success|error"}`
- `rebalancer_pods_analyzed_total`
- `rebalancer_pods_deleted_total{type="highest_cpu|lowest_cpu"}`
- `rebalancer_execution_duration_seconds`
- `rebalancer_cpu_variance_current`
- `rebalancer_cpu_usage_mean`
- `rebalancer_cpu_usage_stddev`

### Critical Alerts
- Consecutive execution failures (3+)
- No pods found matching selector
- Excessive pod deletions (>50% of pods)
- High CPU variance persisting (>threshold for 30+ minutes)
- CPU metrics collection failures

This simplified CPU-focused plan delivers a production-ready stateless application in 7 focused commits, with each commit building working functionality incrementally. Future iterations can add Kafka lag and memory metrics if needed.

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

