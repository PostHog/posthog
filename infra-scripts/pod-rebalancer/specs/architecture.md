# Pod Rebalancer - CPU-Only Architecture

## Core Abstractions (Simplified Design)

This is a stateless application that runs once, fetches CPU metrics using sophisticated PromQL queries, makes HPA-aware decisions, takes actions, and exits.

**Architecture Decision**: Focus exclusively on CPU metrics with a simplified 2-layer design. PromQL queries handle filtering and selection directly, eliminating the need for complex Go-based aggregation logic.

### Layer 1: Generic Metrics Client (`pkg/prometheus/`)
**Responsibility**: Basic Prometheus/VictoriaMetrics HTTP client functionality

```go
// Custom HTTP client for Prometheus queries
type PrometheusClient interface {
    Query(ctx context.Context, query string) (model.Value, error)
}

// HTTPClient implements Client using custom HTTP client
type HTTPClient struct {
    client   *http.Client
    endpoint string
    timeout  time.Duration
}
```

### Layer 2: Specialized CPU Metrics Fetcher (`pkg/metrics/`)
**Responsibility**: Execute sophisticated PromQL queries for HPA-aware pod selection

```go
// CPUMetrics implements specialized queries for the rebalancing algorithm
type CPUMetrics struct {
    client         PrometheusClient
    logger         *zap.Logger
    namespace      string
    deploymentName string
    timeWindow     time.Duration
}

// Interface focuses on exactly what we need
type CPUMetricsFetcher interface {
    FetchCPULimits(ctx context.Context) (float64, error)
    FetchCPURequests(ctx context.Context) (float64, error)
    FetchTopKPodsAboveTolerance(ctx context.Context, k int, toleranceMultiplier float64, hpaPrefix string) (map[string]float64, error)
    FetchBottomKPods(ctx context.Context, k int) (map[string]float64, error)
}

// Key queries that do the heavy lifting in PromQL:
// 1. Top K pods above tolerance threshold with HPA integration
// 2. Bottom K pods for balancing
```

### Layer 3: HPA-Aware Decision Engine (`pkg/decision/`)
**Responsibility**: Execute the sophisticated tolerance-based rebalancing algorithm

```go
// Engine uses the two specialized PromQL queries to make decisions
type Engine struct {
    cpuFetcher               metrics.CPUMetricsFetcher
    topKPods                 int
    toleranceMultiplier      float64
    minimumImprovementPercent float64
    hpaPrefix                string
    logger                   *zap.Logger
}

// Analysis contains the decision results
type Analysis struct {
    ShouldRebalance    bool
    TargetPods         []string
    FilteredTopPods    map[string]float64  // Only pods above tolerance
    BottomPods         map[string]float64  // Bottom K pods
    Reason             string
    Metrics            AnalysisMetrics
}

func (e *Engine) Analyze(ctx context.Context) (*Analysis, error) {
    // 1. Query top K pods above tolerance threshold (PromQL filtering)
    // 2. Query bottom K pods
    // 3. Calculate improvement potential
    // 4. Make decision based on improvement percentage
}
```

### Layer 4: Pod Operations (`pkg/kubernetes/`)
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

### Layer 5: Simple Observability (`pkg/logging/`)
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
│   │   ├── client.go                    # Prometheus HTTP client
│   │   ├── client_ginkgo_test.go        # Ginkgo BDD tests
│   │   └── prometheus_suite_test.go     # Ginkgo test suite
│   ├── metrics/
│   │   ├── cpu.go                       # Specialized CPU queries with PromQL filtering
│   │   ├── interfaces.go                # CPUMetricsFetcher interface
│   │   ├── cpu_ginkgo_test.go           # Ginkgo BDD tests
│   │   └── metrics_suite_test.go        # Ginkgo test suite
│   ├── decision/
│   │   ├── engine.go                    # HPA-aware rebalancing algorithm
│   │   ├── engine_test.go               # Tests for decision logic
│   │   └── decision_suite_test.go       # Ginkgo test suite
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

## Simplified Data Flow

```
[main.go] - Load config from env vars with Viper
    ↓
[prometheus.Client] - Create Prometheus HTTP client  
    ↓
[metrics.CPUMetrics] - Execute specialized PromQL queries
    ├─ FetchTopKPodsAboveTolerance() - Get filtered top pods via PromQL
    ├─ FetchBottomKPods() - Get bottom pods via PromQL
    └─ FetchCPURequests() - Get resource info for calculations
    ↓
[decision.Engine] - Analyze with HPA-aware algorithm
    ├─ Calculate improvement potential from query results
    ├─ Apply tolerance and improvement thresholds
    └─ Make rebalancing decision
    ↓ (if improvement > minimum threshold)
[kubernetes.Manager] - Delete selected pods (or dry-run)
    ↓
[logging.Logger] - Log detailed results and exit
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

# HPA-Aware Decision Making  
REBALANCE_TOP_K_PODS=2                      # Number of top/bottom candidate pods
TOLERANCE_MULTIPLIER=1.5                    # Only act on pods above 150% of HPA target
MINIMUM_IMPROVEMENT_PERCENT=10              # Minimum improvement required (% of top pod average)
HPA_PREFIX=keda-hpa-                        # Optional prefix for HPA name

# Safety & Logging
DRY_RUN=false
LOG_LEVEL=info
```

## HPA-Aware Main Application Flow

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
    
    // 3. Create Prometheus HTTP client
    promClient, err := prometheus.NewClient(config.PrometheusEndpoint, config.PrometheusTimeout)
    if err != nil {
        logger.Fatal("Failed to create Prometheus client", zap.Error(err))
    }
    
    // 4. Create CPU metrics fetcher with specialized queries
    cpuMetrics := metrics.NewCPUMetrics(
        promClient, logger, 
        config.KubeNamespace, config.DeploymentName, config.MetricsTimeWindow,
    )
    
    // 5. Create HPA-aware decision engine (no aggregator needed)
    engine := decision.NewEngine(
        cpuMetrics, config.RebalanceTopKPods, config.ToleranceMultiplier,
        config.MinimumImprovementPercent, config.HPAPrefix, logger,
    )
    
    // 6. Execute sophisticated rebalancing analysis
    analysis, err := engine.Analyze(ctx)
    if err != nil {
        logger.Fatal("Failed to analyze pods for rebalancing", zap.Error(err))
    }
    
    // 7. Execute deletions if improvement exceeds minimum threshold
    if analysis.ShouldRebalance {
        k8sManager := kubernetes.NewManager(config.KubeNamespace, config.DryRun)
        result, err := k8sManager.DeletePods(ctx, analysis.TargetPods)
        if err != nil {
            logger.Fatal("Failed to delete pods", zap.Error(err))
        }
        logger.Info("Rebalancing completed", 
            zap.Strings("deleted_pods", analysis.TargetPods),
            zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent))
    } else {
        logger.Info("No rebalancing needed", 
            zap.String("reason", analysis.Reason),
            zap.Float64("improvement_percent", analysis.Metrics.ImprovementPercent))
    }
}
```

## Testing Strategy (Ginkgo BDD Framework)

### Unit Tests (per package using Ginkgo)
1. **prometheus**: HTTP client, error handling, response parsing with testify mocks
2. **metrics**: Specialized PromQL queries with mocked Prometheus responses
3. **decision**: HPA-aware algorithm with tolerance filtering and improvement calculations
4. **kubernetes**: Pod deletion logic with mocked K8s client
5. **config**: Environment variable parsing with Viper and validation

### Test Framework Features
- **Ginkgo BDD**: Descriptive test organization with Describe/Context/It blocks
- **Gomega**: Rich assertion library for clear test expectations
- **Testify Mocks**: Professional mocking for external dependencies
- **Interface Testing**: Focus on behavior, not struct properties

### Integration Tests
1. **PromQL Queries + Real Prometheus**: End-to-end query validation
2. **Kubernetes + Test Cluster**: Actual pod operations
3. **Full Algorithm Pipeline**: Complete run with realistic CPU data

### Key Testing Principles
- Mock external dependencies (Prometheus, Kubernetes APIs) using testify
- Test with realistic CPU usage data (1000+ pods)
- Validate HPA-aware algorithm calculations with known datasets
- Test error scenarios (network failures, missing CPU metrics)
- Focus on interface behavior rather than internal struct properties

## Error Handling Strategy

Simple error handling for a stateless application:

1. **Fail Fast**: Any critical error causes immediate exit with error code
2. **Structured Logging**: All errors logged with context for debugging
3. **Graceful Degradation**: Skip pods with missing metrics rather than failing completely
4. **No Retries**: Let Kubernetes CronJob handle retries at the job level

This simplified architecture ensures:
- **Stateless**: No state maintained between runs
- **Simple**: Just 2-3 layers, PromQL does the heavy lifting
- **Testable**: Clean interfaces tested with Ginkgo BDD framework
- **Scalable**: Handles 1000+ pods efficiently via PromQL filtering
- **Observable**: Comprehensive logging with structured metrics
- **HPA-Aware**: Uses same target utilization as Kubernetes HPA
- **Sophisticated**: Tolerance-based filtering with improvement calculations
- **Future-Ready**: Designed for easy Kafka lag integration (iteration 2)