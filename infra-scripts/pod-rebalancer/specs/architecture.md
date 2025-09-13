# Pod Rebalancer - CPU-Only Architecture

## Core Abstractions (Layered Design)

This is a stateless application that runs once, fetches CPU metrics, makes decisions based on CPU load variance, takes actions, and exits.

**Architecture Decision**: Focus exclusively on CPU metrics for initial implementation to reduce complexity and deliver faster. Kafka lag and memory metrics can be added in future iterations if needed.

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

### Layer 2: CPU Metrics Fetcher (`pkg/metrics/`)
**Responsibility**: Fetch CPU usage metrics from Prometheus

```go
// CPUMetricsFetcher gets CPU usage per pod using PostHog-specific queries
type CPUMetricsFetcher struct {
    client         PrometheusClient
    logger         *zap.Logger
    namespace      string
    deploymentName string
    timeWindow     time.Duration
}

func (f *CPUMetricsFetcher) FetchCPUUsage(ctx context.Context) (map[string]float64, error)
func (f *CPUMetricsFetcher) FetchCPULimits(ctx context.Context) (float64, error)
func (f *CPUMetricsFetcher) FetchCPURequests(ctx context.Context) (float64, error)

// Main CPU usage query uses literal container matching
// sum by(pod) (rate(container_cpu_usage_seconds_total{namespace="posthog", container="ingestion-consumer"}[5m]))
```

### Layer 3: Pod State Aggregator (`pkg/podstate/`)
**Responsibility**: Process CPU metrics into pod states

```go
// Aggregator processes CPU metrics into pod states
type Aggregator struct {
    cpuFetcher metrics.CPUMetricsFetcher
    logger     *zap.Logger
}

// PodState represents CPU metrics for a single pod (simplified)
type PodState struct {
    Name      string
    CPUUsage  float64  // CPU cores per second
    CPUScore  float64  // Direct CPU usage as score
}

func (a *Aggregator) GetPodStates(ctx context.Context) ([]PodState, error) {
    // Fetch CPU usage metrics
    // Convert to PodState objects
    // CPU usage directly becomes the score (simplified scoring)
}
```

### Layer 4: Decision Engine (`pkg/decision/`)
**Responsibility**: Analyze CPU usage and decide which pods to delete

```go
// Engine analyzes CPU usage and selects pods for deletion
type Engine struct {
    cpuVarianceThreshold float64
    logger              *zap.Logger
}

// Analysis contains the CPU-based decision results
type Analysis struct {
    PodStates       []podstate.PodState
    ShouldRebalance bool
    TargetPods      []string
    Reason          string
    CPUStatistics   CPUStatistics
}

// CPUStatistics contains statistical analysis of CPU usage
type CPUStatistics struct {
    Mean     float64
    StdDev   float64
    Variance float64
    Min      float64
    Max      float64
}

func (e *Engine) Analyze(ctx context.Context, podStates []podstate.PodState) (*Analysis, error) {
    // Calculate CPU variance across pods
    // Determine if CPU variance exceeds threshold
    // Select highest and lowest CPU usage pods for deletion
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
│   │   ├── client.go                    # Prometheus client using custom HTTP client
│   │   ├── client_ginkgo_test.go        # Ginkgo BDD tests
│   │   └── prometheus_suite_test.go     # Ginkgo test suite
│   ├── metrics/
│   │   ├── cpu.go                       # CPU metrics fetcher (CPU-only focus)
│   │   ├── cpu_ginkgo_test.go           # Ginkgo BDD tests
│   │   └── metrics_suite_test.go        # Ginkgo test suite
│   ├── podstate/
│   │   ├── aggregator.go                # Processes CPU metrics into PodState
│   │   └── aggregator_test.go           # Tests for CPU aggregation
│   ├── decision/
│   │   ├── engine.go                    # CPU variance-based decision logic
│   │   └── engine_test.go               # Tests for CPU decision making
│   ├── kubernetes/
│   │   ├── manager.go                   # Pod operations using official k8s client
│   │   └── manager_test.go
│   ├── config/
│   │   ├── env.go                       # Environment configuration with Viper
│   │   ├── env_ginkgo_test.go           # Ginkgo BDD tests
│   │   └── config_suite_test.go         # Ginkgo test suite
│   └── logging/
│       ├── logger.go                    # Structured logging with zap
│       ├── metrics.go                   # Prometheus metrics using official client
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

## CPU-Only Data Flow

```
[main.go] - Load config from env vars with Viper
    ↓
[prometheus.Client] - Create Prometheus client with custom HTTP client
    ↓
[metrics.CPUMetricsFetcher] - Fetch CPU usage per pod using PostHog queries
    ↓ 
[podstate.Aggregator] - Process CPU metrics into PodState objects
    ↓
[decision.Engine] - Calculate CPU variance and statistics
    ↓ (if CPU variance > threshold)
[decision.Engine] - Select highest & lowest CPU usage pods
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

# Kubernetes & Metrics
KUBE_NAMESPACE=posthog
KUBE_LABEL_SELECTOR=app=consumer
DEPLOYMENT_NAME=ingestion-consumer          # Required - container name for literal matching
METRICS_TIME_WINDOW=5m                      # Time window for rate calculations

# CPU-Only Decision Making
CPU_VARIANCE_THRESHOLD=0.3                  # Threshold for CPU variance to trigger rebalancing
MIN_PODS_REQUIRED=3                         # Minimum pods that must remain

# Safety & Logging
DRY_RUN=false
LOG_LEVEL=info
```

## CPU-Only Main Application Flow

```go
func main() {
    ctx := context.Background()
    
    // 1. Load configuration from environment using Viper
    config, err := config.LoadFromEnv()
    if err != nil {
        log.Fatalf("Failed to load configuration: %v", err)
    }
    
    // 2. Create zap logger
    logger := logging.New(config.LogLevel)
    
    // 3. Create Prometheus client with custom HTTP client
    promClient, err := prometheus.NewClient(config.PrometheusEndpoint, config.PrometheusTimeout)
    if err != nil {
        logger.Fatal("Failed to create Prometheus client", zap.Error(err))
    }
    
    // 4. Create CPU metrics fetcher
    cpuFetcher := metrics.NewCPUMetricsFetcher(
        promClient, logger, 
        config.KubeNamespace, config.DeploymentName, config.MetricsTimeWindow,
    )
    
    // 5. Create aggregator (CPU-only)
    aggregator := podstate.NewAggregator(cpuFetcher, logger)
    
    // 6. Fetch and process CPU metrics
    podStates, err := aggregator.GetPodStates(ctx)
    if err != nil {
        logger.Fatal("Failed to fetch CPU metrics", zap.Error(err))
    }
    
    // 7. Make CPU variance-based rebalancing decision
    engine := decision.NewEngine(config.CPUVarianceThreshold, logger)
    analysis, err := engine.Analyze(ctx, podStates)
    if err != nil {
        logger.Fatal("Failed to analyze CPU data", zap.Error(err))
    }
    
    // 8. Execute deletions if CPU variance exceeds threshold
    if analysis.ShouldRebalance {
        k8sManager := kubernetes.NewManager(config.KubeNamespace, config.DryRun, config.MinPodsRequired)
        result, err := k8sManager.DeletePods(ctx, analysis.TargetPods)
        if err != nil {
            logger.Fatal("Failed to delete pods", zap.Error(err))
        }
        logger.Info("Rebalancing completed", 
            zap.Strings("deleted_pods", analysis.TargetPods),
            zap.Float64("cpu_variance", analysis.CPUStatistics.Variance))
    } else {
        logger.Info("No rebalancing needed", 
            zap.Float64("cpu_variance", analysis.CPUStatistics.Variance),
            zap.Float64("threshold", config.CPUVarianceThreshold))
    }
}
```

## Testing Strategy (Ginkgo BDD Framework)

### Unit Tests (per package using Ginkgo)
1. **prometheus**: HTTP client, error handling, response parsing with testify mocks
2. **metrics**: CPU metric fetcher with mocked Prometheus responses using PostHog queries
3. **podstate**: CPU aggregation logic with known CPU usage inputs/outputs
4. **decision**: CPU variance statistical analysis and pod selection algorithms
5. **kubernetes**: Pod deletion logic with mocked K8s client
6. **config**: Environment variable parsing with Viper and validation

### Test Framework Features
- **Ginkgo BDD**: Descriptive test organization with Describe/Context/It blocks
- **Gomega**: Rich assertion library for clear test expectations
- **Testify Mocks**: Professional mocking for external dependencies
- **Interface Testing**: Focus on behavior, not struct properties

### Integration Tests
1. **CPU Metrics + Real Prometheus**: End-to-end CPU metric fetching
2. **Kubernetes + Test Cluster**: Actual pod operations
3. **Full CPU Pipeline**: Complete run with CPU test data

### Key Testing Principles
- Mock external dependencies (Prometheus, Kubernetes APIs) using testify
- Test with realistic CPU usage data (1000+ pods)
- Validate CPU statistical calculations with known datasets
- Test error scenarios (network failures, missing CPU metrics)
- Focus on interface behavior rather than internal struct properties

## Error Handling Strategy

Simple error handling for a stateless application:

1. **Fail Fast**: Any critical error causes immediate exit with error code
2. **Structured Logging**: All errors logged with context for debugging
3. **Graceful Degradation**: Skip pods with missing metrics rather than failing completely
4. **No Retries**: Let Kubernetes CronJob handle retries at the job level

This CPU-focused architecture ensures:
- **Stateless**: No state maintained between runs
- **Simple**: Minimal abstractions, clear data flow, CPU-only focus
- **Testable**: Each layer easily tested in isolation using Ginkgo BDD framework
- **Scalable**: Handles 1000+ pods efficiently with CPU metrics only
- **Observable**: Simple but effective logging and metrics
- **Focused**: Single responsibility - CPU load balancing only
- **Extensible**: Future iterations can add Kafka lag and memory metrics if needed