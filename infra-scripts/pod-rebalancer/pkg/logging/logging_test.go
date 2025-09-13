package logging

import (
	"bytes"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

func TestNew(t *testing.T) {
	tests := []struct {
		name     string
		logLevel string
		wantErr  bool
	}{
		{
			name:     "debug level",
			logLevel: "debug",
			wantErr:  false,
		},
		{
			name:     "info level",
			logLevel: "info",
			wantErr:  false,
		},
		{
			name:     "warn level",
			logLevel: "warn",
			wantErr:  false,
		},
		{
			name:     "error level",
			logLevel: "error",
			wantErr:  false,
		},
		{
			name:     "invalid level falls back to info",
			logLevel: "invalid",
			wantErr:  false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			logger, err := New(tt.logLevel)

			if tt.wantErr {
				require.Error(t, err)
				return
			}

			require.NoError(t, err)
			assert.NotNil(t, logger)
			assert.NotNil(t, logger.zap)
		})
	}
}

func TestLogger_LogMethods(t *testing.T) {
	// Create a logger that writes to a buffer for testing
	var buf bytes.Buffer

	// Create a custom logger with buffer output for testing
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	// Test different log levels
	logger.Debug("debug message", zap.String("key", "value"))
	logger.Info("info message", zap.String("key", "value"))
	logger.Warn("warn message", zap.String("key", "value"))
	logger.Error("error message", zap.String("key", "value"))

	// Sync to flush buffer
	err = logger.Sync()
	require.NoError(t, err)

	// Verify log output contains expected content
	logOutput := buf.String()
	assert.Contains(t, logOutput, "debug message")
	assert.Contains(t, logOutput, "info message")
	assert.Contains(t, logOutput, "warn message")
	assert.Contains(t, logOutput, "error message")
}

func TestLogger_LogExecution(t *testing.T) {
	var buf bytes.Buffer
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	// Test dry run execution
	logger.LogExecution(
		"rebalancing not needed - variance below threshold",
		[]string{},
		map[string]string{},
		true,
	)

	// Test actual execution with deleted pods
	logger.LogExecution(
		"rebalancing completed",
		[]string{"pod-1", "pod-2"},
		map[string]string{"pod-3": "below minimum threshold"},
		false,
	)

	err = logger.Sync()
	require.NoError(t, err)

	logOutput := buf.String()
	assert.Contains(t, logOutput, "dry-run")
	assert.Contains(t, logOutput, "deleted_count")
	assert.Contains(t, logOutput, "skipped_pods")
}

func TestLogger_LogError(t *testing.T) {
	var buf bytes.Buffer
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	testErr := assert.AnError
	context := map[string]interface{}{
		"step":     "metrics_collection",
		"endpoint": "http://prometheus:9090",
		"timeout":  "30s",
	}

	logger.LogError(testErr, context)

	err = logger.Sync()
	require.NoError(t, err)

	logOutput := buf.String()
	assert.Contains(t, logOutput, "Operation failed")
	assert.Contains(t, logOutput, "step")
	assert.Contains(t, logOutput, "endpoint")
}

func TestLogger_LogMetricsCollection(t *testing.T) {
	var buf bytes.Buffer
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	// Test successful collection
	logger.LogMetricsCollection(5, "2.5s", nil)

	// Test collection with errors
	logger.LogMetricsCollection(3, "1.2s", []string{"timeout on pod-1", "missing metrics for pod-2"})

	err = logger.Sync()
	require.NoError(t, err)

	logOutput := buf.String()
	assert.Contains(t, logOutput, "pods_analyzed")
	assert.Contains(t, logOutput, "collection_duration")
	assert.Contains(t, logOutput, "collection_errors")
}

func TestLogger_LogPodAnalysis(t *testing.T) {
	var buf bytes.Buffer
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	// Test analysis indicating rebalancing needed
	logger.LogPodAnalysis(5, 0.45, 0.67, true, "variance exceeds threshold")

	// Test analysis indicating no rebalancing needed
	logger.LogPodAnalysis(3, 0.15, 0.23, false, "variance within acceptable range")

	err = logger.Sync()
	require.NoError(t, err)

	logOutput := buf.String()
	assert.Contains(t, logOutput, "cpu_variance")
	assert.Contains(t, logOutput, "lag_variance")
	assert.Contains(t, logOutput, "should_rebalance")
}

func TestLogger_LogPodSelection(t *testing.T) {
	var buf bytes.Buffer
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	logger.LogPodSelection("pod-high-load", "pod-low-load", 0.89, 0.12)

	err = logger.Sync()
	require.NoError(t, err)

	logOutput := buf.String()
	assert.Contains(t, logOutput, "most_busy_pod")
	assert.Contains(t, logOutput, "least_busy_pod")
	assert.Contains(t, logOutput, "most_busy_score")
	assert.Contains(t, logOutput, "least_busy_score")
}

func TestLogger_With(t *testing.T) {
	var buf bytes.Buffer
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	// Create logger with additional context
	contextLogger := logger.With(
		zap.String("execution_id", "exec-123"),
		zap.String("namespace", "production"),
	)

	contextLogger.Info("test message with context")

	err = contextLogger.Sync()
	require.NoError(t, err)

	logOutput := buf.String()
	assert.Contains(t, logOutput, "execution_id")
	assert.Contains(t, logOutput, "namespace")
}

// createTestLogger creates a logger that writes to the given buffer for testing
func createTestLogger(buf *bytes.Buffer) (*Logger, error) {
	// Create encoder config
	encoderConfig := zapcore.EncoderConfig{
		LevelKey:       "level",
		MessageKey:     "msg",
		EncodeLevel:    zapcore.LowercaseLevelEncoder,
		EncodeTime:     zapcore.ISO8601TimeEncoder,
		EncodeDuration: zapcore.SecondsDurationEncoder,
	}

	// Create core with buffer output
	core := zapcore.NewCore(
		zapcore.NewJSONEncoder(encoderConfig),
		zapcore.AddSync(buf),
		zapcore.DebugLevel,
	)

	// Create logger
	zapLogger := zap.New(core)

	return &Logger{
		zap: zapLogger,
	}, nil
}

func TestLogger_JSONOutput(t *testing.T) {
	var buf bytes.Buffer
	logger, err := createTestLogger(&buf)
	require.NoError(t, err)

	logger.Info("test message", zap.String("key", "value"))
	err = logger.Sync()
	require.NoError(t, err)

	// Verify output is valid JSON
	var logEntry map[string]interface{}
	err = json.Unmarshal(buf.Bytes(), &logEntry)
	require.NoError(t, err)

	// Verify expected fields
	assert.Equal(t, "info", logEntry["level"])
	assert.Equal(t, "test message", logEntry["msg"])
	assert.Equal(t, "value", logEntry["key"])
}
