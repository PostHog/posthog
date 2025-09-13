# Pod Rebalancer - Simplified Architecture

## Core Abstractions (Layered Design)

This is a stateless application that runs once, fetches metrics, makes decisions, takes actions, and exits.

### Layer 1: Generic Metrics Client (`pkg/prometheus/`)
**Responsibility**: Basic Prometheus/VictoriaMetrics client functionality

```go
// Using official Prometheus Go client
import (
    "github.com/prometheus/client_golang/api"
    v1 "github.com/prometheus/client_golang/api/prometheus/v1"
    "github.com/prometheus/common/model"
)

// Client wraps the official Prometheus API client
type Client interface {
    Query(ctx context.Context, query string) (model.Value, error)
    QueryRange(ctx context.Context, query string, r v1.Range) (model.Value, error)
}

// HTTPClient implements Client using official Prometheus client
type HTTPClient struct {
    client   v1.API
    timeout  time.Duration
}
```

### Layer 2: Concrete Metrics Fetchers (`pkg/metrics/`)
**Responsibility**: Fetch specific metric types from Prometheus

```go
// CPUMetricsFetcher gets CPU usage per pod
type CPUMetricsFetcher struct {
    client prometheus.Client
}
func (f *CPUMetricsFetcher) Fetch(ctx context.Context, podSelector string) (map[string]float64, error)

// KafkaMetricsFetcher gets Kafka lag and consumption rate per pod  
type KafkaMetricsFetcher struct {
    client prometheus.Client
}
func (f *KafkaMetricsFetcher) Fetch(ctx context.Context, podSelector string) (map[string]KafkaMetrics, error)

// MemoryMetricsFetcher gets memory usage per pod
type MemoryMetricsFetcher struct {
    client prometheus.Client
}
func (f *MemoryMetricsFetcher) Fetch(ctx context.Context, podSelector string) (map[string]float64, error)
```

### Layer 3: Pod State Aggregator (`pkg/podstate/`)
**Responsibility**: Combine all metrics into unified pod state

```go
// Aggregator combines various metrics into pod states
type Aggregator struct {
    cpuFetcher    metrics.CPUMetricsFetcher
    kafkaFetcher  metrics.KafkaMetricsFetcher
    memoryFetcher metrics.MemoryMetricsFetcher
}

// PodState represents all metrics for a single pod
type PodState struct {
    Name            string
    CPUUsage        float64
    MemoryUsage     float64
    KafkaLag        int64
    MessageRate     float64
    CompositeScore  float64
}

func (a *Aggregator) GetPodStates(ctx context.Context, podSelector string) ([]PodState, error) {
    // Fetch all metric types in parallel
    // Combine into unified PodState objects
    // Calculate composite scores
}
```

### Layer 4: Decision Engine (`pkg/decision/`)
**Responsibility**: Analyze pod states and decide which pods to delete

```go
// Engine analyzes pod states and selects outlier pods for deletion
type Engine struct {
    thresholds Thresholds
}

// Analysis contains the decision results
type Analysis struct {
    PodStates       []podstate.PodState
    ShouldRebalance bool
    TargetPods      []string
    Reason          string
    Statistics      Statistics
}

func (e *Engine) Analyze(ctx context.Context, podStates []podstate.PodState) (*Analysis, error) {
    // Calculate load statistics (variance, std dev)
    // Determine if rebalancing is needed based on thresholds
    // Select most busy and least busy pods for deletion
}

```

### Layer 5: Pod Operations (`pkg/kubernetes/`)
**Responsibility**: Execute pod deletions safely

```go
// Using official Kubernetes Go client
import (
    "k8s.io/client-go/kubernetes"
    v1 "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// PodManager handles Kubernetes pod operations
type PodManager struct {
    client    kubernetes.Interface
    namespace string
    dryRun    bool
}

// DeletionResult tracks what happened during deletions
type DeletionResult struct {
    Attempted []string
    Deleted   []string
    Skipped   map[string]string // pod name -> skip reason
    Errors    map[string]error  // pod name -> error
}

func (pm *PodManager) DeletePods(ctx context.Context, podNames []string) (*DeletionResult, error) {
    // Use client.CoreV1().Pods(namespace).Delete() for actual deletions
    // Validate each pod can be safely deleted
    // Execute deletions (or log for dry-run)
    // Return detailed results
}
```

### Layer 6: Simple Observability (`pkg/logging/`)
**Responsibility**: Basic structured logging and metrics

```go
// Using zap for high-performance structured logging
import "go.uber.org/zap"

// Logger provides structured logging
type Logger struct {
    logger *zap.Logger
}

func (l *Logger) LogExecution(analysis *decision.Analysis, result *kubernetes.DeletionResult)
func (l *Logger) LogError(err error, context map[string]interface{})

// Using official Prometheus client
import "github.com/prometheus/client_golang/prometheus"

type Metrics struct {
    podsAnalyzed   prometheus.CounterVec
    podsDeleted    prometheus.CounterVec  
    executionTime  prometheus.Histogram
    loadVariance   prometheus.Gauge
}
```

## Enhanced Package Structure with Go Best Practices

```
pod-rebalancer/
├── .envrc                        # Development environment variables (direnv)
├── .golangci.yml                 # Golangci-lint configuration
├── .gitignore                    # Git ignore patterns
├── tools.go                      # Tool dependencies management
├── Taskfile.yml                  # Build automation with go-task/task
├── go.mod                        # Go module definition
├── go.sum                        # Dependency checksums
├── README.md                     # Project documentation
├── cmd/
│   └── rebalancer/
│       └── main.go               # Application entrypoint - run once and exit
├── pkg/
│   ├── prometheus/
│   │   ├── client.go             # Prometheus client using official libraries
│   │   └── client_test.go
│   ├── metrics/
│   │   ├── cpu.go                # CPU metrics fetcher
│   │   ├── kafka.go              # Kafka metrics fetcher
│   │   ├── memory.go             # Memory metrics fetcher
│   │   └── metrics_test.go
│   ├── podstate/
│   │   ├── aggregator.go         # Combines metrics into PodState
│   │   └── aggregator_test.go
│   ├── decision/
│   │   ├── engine.go             # Decision making logic
│   │   ├── outliers.go           # Outlier rotation strategy
│   │   └── decision_test.go
│   ├── kubernetes/
│   │   ├── manager.go            # Pod operations using official k8s client
│   │   └── manager_test.go
│   ├── config/
│   │   ├── env.go                # Environment variable configuration
│   │   └── env_test.go
│   └── logging/
│       ├── logger.go             # Structured logging with zap
│       ├── metrics.go            # Prometheus metrics using official client
│       └── logging_test.go
├── internal/
│   └── testutil/
│       └── mocks.go              # Test mocks and fixtures
├── scripts/
│   └── install-tools.sh          # Development setup script
├── docs/
│   ├── development.md            # Development setup and workflow
│   ├── architecture.md           # Technical architecture (this document)
│   └── deployment.md             # Deployment guide
├── examples/
│   └── docker-compose.yml        # Local development environment
└── deploy/
    └── docker/
        └── Dockerfile            # Multi-stage optimized Dockerfile
```

## Simplified Data Flow

```
[main.go] - Load config from env vars
    ↓
[prometheus.Client] - Create Prometheus client
    ↓
[metrics.*Fetcher] - Fetch CPU, Kafka, Memory metrics in parallel
    ↓ 
[podstate.Aggregator] - Combine metrics into PodState objects
    ↓
[decision.Engine] - Analyze states, decide if rebalancing needed
    ↓ (if needed)
[decision.Engine] - Select pods based on strategy
    ↓
[kubernetes.Manager] - Delete selected pods (or dry-run)
    ↓
[logging.Logger] - Log results and exit
```

## Configuration (Environment Variables Only)

```bash
# Prometheus/VictoriaMetrics
PROMETHEUS_ENDPOINT=http://victoriametrics:8428
PROMETHEUS_TIMEOUT=30s

# Kubernetes
KUBE_NAMESPACE=default
KUBE_LABEL_SELECTOR=app=consumer

# Decision making
# Strategy is always rotate_outliers (delete most busy + least busy pods)
CPU_VARIANCE_THRESHOLD=0.3
LAG_VARIANCE_THRESHOLD=0.5
# Always deletes exactly 2 pods (most busy + least busy)
MIN_PODS_REQUIRED=3

# Safety
DRY_RUN=false
```

## Main Application Flow

```go
func main() {
    ctx := context.Background()
    
    // 1. Load configuration from environment
    config := config.LoadFromEnv()
    
    // 2. Create zap logger
    logger := logging.New()
    
    // 3. Create official Prometheus client
    promClient := prometheus.NewHTTPClient(config.PrometheusEndpoint, config.Timeout)
    
    // 4. Create metrics fetchers
    cpuFetcher := metrics.NewCPUFetcher(promClient)
    kafkaFetcher := metrics.NewKafkaFetcher(promClient)
    memoryFetcher := metrics.NewMemoryFetcher(promClient)
    
    // 5. Create aggregator
    aggregator := podstate.NewAggregator(cpuFetcher, kafkaFetcher, memoryFetcher)
    
    // 6. Fetch and aggregate pod states
    podStates, err := aggregator.GetPodStates(ctx, config.LabelSelector)
    if err != nil {
        logger.LogError(err, map[string]interface{}{"step": "fetch_metrics"})
        os.Exit(1)
    }
    
    // 7. Make rebalancing decision
    engine := decision.NewEngine(config.Thresholds)
    analysis, err := engine.Analyze(ctx, podStates)
    if err != nil {
        logger.LogError(err, map[string]interface{}{"step": "analysis"})
        os.Exit(1)
    }
    
    // 8. Execute deletions if needed
    if analysis.ShouldRebalance {
        k8sManager := kubernetes.NewManager(config.Namespace, config.DryRun)
        result, err := k8sManager.DeletePods(ctx, analysis.TargetPods)
        if err != nil {
            logger.LogError(err, map[string]interface{}{"step": "deletion"})
            os.Exit(1)
        }
        logger.LogExecution(analysis, result)
    } else {
        logger.LogExecution(analysis, nil)
    }
    
    // 9. Exit cleanly
    os.Exit(0)
}
```

## Testing Strategy

### Unit Tests (per package)
1. **prometheus**: HTTP client, error handling, response parsing
2. **metrics**: Individual metric fetchers with mocked Prometheus responses
3. **podstate**: Aggregation logic with known inputs/outputs
4. **decision**: Statistical analysis and strategy selection algorithms
5. **kubernetes**: Pod deletion logic with mocked K8s client
6. **config**: Environment variable parsing and validation

### Integration Tests
1. **Metrics + Real Prometheus**: End-to-end metric fetching
2. **Kubernetes + Test Cluster**: Actual pod operations
3. **Full Pipeline**: Complete run with test data

### Key Testing Principles
- Mock external dependencies (Prometheus, Kubernetes APIs)
- Test with realistic data volumes (1000+ pods)
- Validate statistical calculations with known datasets
- Test error scenarios (network failures, missing metrics)

## Error Handling Strategy

Simple error handling for a stateless application:

1. **Fail Fast**: Any critical error causes immediate exit with error code
2. **Structured Logging**: All errors logged with context for debugging
3. **Graceful Degradation**: Skip pods with missing metrics rather than failing completely
4. **No Retries**: Let Kubernetes CronJob handle retries at the job level

This simplified architecture ensures:
- **Stateless**: No state maintained between runs
- **Simple**: Minimal abstractions, clear data flow
- **Testable**: Each layer easily tested in isolation
- **Scalable**: Handles 1000+ pods efficiently
- **Observable**: Simple but effective logging and metrics