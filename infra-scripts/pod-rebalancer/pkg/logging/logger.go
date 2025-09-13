package logging

import (
	"os"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// Logger provides structured logging capabilities using zap
type Logger struct {
	zap *zap.Logger
}

// New creates a new logger with the specified log level
func New(logLevel string) (*Logger, error) {
	// Parse log level
	level, err := zapcore.ParseLevel(logLevel)
	if err != nil {
		// Fallback to info level if parsing fails
		level = zapcore.InfoLevel
	}

	// Create encoder config for structured logging
	encoderConfig := zapcore.EncoderConfig{
		TimeKey:        "timestamp",
		LevelKey:       "level",
		NameKey:        "logger",
		CallerKey:      "caller",
		FunctionKey:    zapcore.OmitKey,
		MessageKey:     "msg",
		StacktraceKey:  "stacktrace",
		LineEnding:     zapcore.DefaultLineEnding,
		EncodeLevel:    zapcore.LowercaseLevelEncoder,
		EncodeTime:     zapcore.ISO8601TimeEncoder,
		EncodeDuration: zapcore.SecondsDurationEncoder,
		EncodeCaller:   zapcore.ShortCallerEncoder,
	}

	// Create core with console encoder
	core := zapcore.NewCore(
		zapcore.NewJSONEncoder(encoderConfig),
		zapcore.AddSync(os.Stdout),
		level,
	)

	// Create logger
	zapLogger := zap.New(core, zap.AddCaller())

	return &Logger{
		zap: zapLogger,
	}, nil
}

// Debug logs a debug message with structured fields
func (l *Logger) Debug(msg string, fields ...zap.Field) {
	l.zap.Debug(msg, fields...)
}

// Info logs an info message with structured fields
func (l *Logger) Info(msg string, fields ...zap.Field) {
	l.zap.Info(msg, fields...)
}

// Warn logs a warning message with structured fields
func (l *Logger) Warn(msg string, fields ...zap.Field) {
	l.zap.Warn(msg, fields...)
}

// Error logs an error message with structured fields
func (l *Logger) Error(msg string, fields ...zap.Field) {
	l.zap.Error(msg, fields...)
}

// LogExecution logs the results of a complete rebalancing execution
func (l *Logger) LogExecution(analysisResult string, deletedPods []string, skippedPods map[string]string, dryRun bool) {
	fields := []zap.Field{
		zap.String("analysis_result", analysisResult),
		zap.Strings("deleted_pods", deletedPods),
		zap.Int("deleted_count", len(deletedPods)),
		zap.Bool("dry_run", dryRun),
	}

	if len(skippedPods) > 0 {
		skippedReasons := make([]string, 0, len(skippedPods))
		for pod, reason := range skippedPods {
			skippedReasons = append(skippedReasons, pod+": "+reason)
		}
		fields = append(fields, zap.Strings("skipped_pods", skippedReasons))
	}

	if dryRun {
		l.Info("Pod rebalancing execution completed (dry-run)", fields...)
	} else {
		l.Info("Pod rebalancing execution completed", fields...)
	}
}

// LogError logs an error with additional context
func (l *Logger) LogError(err error, context map[string]interface{}) {
	fields := []zap.Field{zap.Error(err)}

	// Convert context map to zap fields
	for key, value := range context {
		fields = append(fields, zap.Any(key, value))
	}

	l.Error("Operation failed", fields...)
}

// LogMetricsCollection logs the results of metrics collection
func (l *Logger) LogMetricsCollection(podCount int, duration string, errors []string) {
	fields := []zap.Field{
		zap.Int("pods_analyzed", podCount),
		zap.String("collection_duration", duration),
	}

	if len(errors) > 0 {
		fields = append(fields, zap.Strings("collection_errors", errors))
		l.Warn("Metrics collection completed with errors", fields...)
	} else {
		l.Info("Metrics collection completed successfully", fields...)
	}
}

// LogPodAnalysis logs the statistical analysis results
func (l *Logger) LogPodAnalysis(podCount int, cpuVariance, lagVariance float64, shouldRebalance bool, reason string) {
	fields := []zap.Field{
		zap.Int("pod_count", podCount),
		zap.Float64("cpu_variance", cpuVariance),
		zap.Float64("lag_variance", lagVariance),
		zap.Bool("should_rebalance", shouldRebalance),
		zap.String("reason", reason),
	}

	if shouldRebalance {
		l.Info("Analysis indicates rebalancing is needed", fields...)
	} else {
		l.Info("Analysis indicates no rebalancing needed", fields...)
	}
}

// LogPodSelection logs which pods were selected for deletion
func (l *Logger) LogPodSelection(mostBusyPod, leastBusyPod string, mostBusyScore, leastBusyScore float64) {
	fields := []zap.Field{
		zap.String("most_busy_pod", mostBusyPod),
		zap.Float64("most_busy_score", mostBusyScore),
		zap.String("least_busy_pod", leastBusyPod),
		zap.Float64("least_busy_score", leastBusyScore),
	}

	l.Info("Selected pods for outlier rotation", fields...)
}

// Sync flushes any buffered log entries
func (l *Logger) Sync() error {
	return l.zap.Sync()
}

// With creates a new logger with additional context fields
func (l *Logger) With(fields ...zap.Field) *Logger {
	return &Logger{
		zap: l.zap.With(fields...),
	}
}
