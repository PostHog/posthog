package metrics

import (
	"context"
	"errors"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/stdout/stdoutlog"
	"go.opentelemetry.io/otel/exporters/stdout/stdoutmetric"
	"go.opentelemetry.io/otel/exporters/stdout/stdouttrace"
	"go.opentelemetry.io/otel/log/global"
	"go.opentelemetry.io/otel/propagation"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	"go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/trace"

	"github.com/posthog/posthog/livestream/configs"
)

// SetupOTelSDK bootstraps the OpenTelemetry pipeline.
// If it does not return an error, make sure to call shutdown for proper cleanup.
func SetupOTelSDK(ctx context.Context, otelConfig *configs.OtelConfig) (shutdown func(context.Context) error, err error) {
	var shutdownFuncs []func(context.Context) error

	// shutdown calls cleanup functions registered via shutdownFuncs.
	// The errors from the calls are joined.
	// Each registered cleanup will be invoked once.
	shutdown = func(ctx context.Context) error {
		var err error
		for _, fn := range shutdownFuncs {
			err = errors.Join(err, fn(ctx))
		}
		shutdownFuncs = nil
		return err
	}

	// handleErr calls shutdown for cleanup and makes sure that all errors are returned.
	handleErr := func(inErr error) {
		err = errors.Join(inErr, shutdown(ctx))
	}

	// Set up propagator.
	prop := newPropagator()
	otel.SetTextMapPropagator(prop)

	// Set up trace provider.
	// Console output for traces is controlled by otelConfig.ConsoleEnabled
	tracerProvider, err := newTracerProvider(otelConfig.ConsoleEnabled)
	if err != nil {
		handleErr(err)
		return
	}
	shutdownFuncs = append(shutdownFuncs, tracerProvider.Shutdown)
	otel.SetTracerProvider(tracerProvider)

	// Set up meter provider.
	// Console output for metrics is always disabled regardless of otelConfig.ConsoleEnabled
	meterProvider, err := newMeterProvider(false)
	if err != nil {
		handleErr(err)
		return
	}
	shutdownFuncs = append(shutdownFuncs, meterProvider.Shutdown)
	otel.SetMeterProvider(meterProvider)

	// Set up logger provider.
	// Console output for logs is always disabled regardless of otelConfig.ConsoleEnabled
	loggerProvider, err := newLoggerProvider(false)
	if err != nil {
		handleErr(err)
		return
	}
	shutdownFuncs = append(shutdownFuncs, loggerProvider.Shutdown)
	global.SetLoggerProvider(loggerProvider)

	return
}

func newPropagator() propagation.TextMapPropagator {
	return propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	)
}

// newTracerProvider now only takes consoleEnabled bool
func newTracerProvider(consoleEnabled bool) (*trace.TracerProvider, error) {
	if !consoleEnabled {
		// log.Println("No trace exporter enabled, using no-op provider.") // Can keep or remove this log
		return trace.NewTracerProvider(), nil
	}

	// log.Println("Console Trace Exporter enabled.") // Can keep or remove this log
	spanExporter, err := stdouttrace.New(stdouttrace.WithPrettyPrint())
	if err != nil {
		// return nil, fmt.Errorf("failed to create stdout trace exporter: %w", err) // Revert fmt if removed
		return nil, err // Simpler error return if fmt is removed
	}

	tracerProvider := trace.NewTracerProvider(
		trace.WithBatcher(spanExporter, trace.WithBatchTimeout(time.Second)),
	)
	return tracerProvider, nil
}

func newMeterProvider(consoleEnabled bool) (*metric.MeterProvider, error) {
	if !consoleEnabled {
		return metric.NewMeterProvider(), nil
	}

	metricExporter, err := stdoutmetric.New()
	if err != nil {
		return nil, err
	}

	meterProvider := metric.NewMeterProvider(
		metric.WithReader(metric.NewPeriodicReader(metricExporter,
			metric.WithInterval(3*time.Second))),
	)
	return meterProvider, nil
}

func newLoggerProvider(consoleEnabled bool) (*sdklog.LoggerProvider, error) {
	if !consoleEnabled {
		return sdklog.NewLoggerProvider(), nil
	}

	logExporter, err := stdoutlog.New()
	if err != nil {
		return nil, err
	}

	loggerProvider := sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewBatchProcessor(logExporter)),
	)
	return loggerProvider, nil
}
