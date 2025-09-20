package prometheus

import (
	"context"
	"fmt"
	"time"

	"github.com/prometheus/client_golang/api"
	v1 "github.com/prometheus/client_golang/api/prometheus/v1"
	"github.com/prometheus/common/model"
	"go.uber.org/zap"

	"github.com/posthog/pod-rebalancer/pkg/logging"
)

// Client wraps the Prometheus API client with convenience methods
type Client struct {
	api     v1.API
	timeout time.Duration
	logger  *logging.Logger
}

// NewClient creates a new Prometheus client with the given endpoint and timeout
func NewClient(endpoint string, timeout time.Duration, logger *logging.Logger) (*Client, error) {
	config := api.Config{
		Address: endpoint,
	}

	client, err := api.NewClient(config)
	if err != nil {
		return nil, fmt.Errorf("failed to create Prometheus client: %w", err)
	}

	return &Client{
		api:     v1.NewAPI(client),
		timeout: timeout,
		logger:  logger,
	}, nil
}

// Query executes a PromQL query and returns the result
func (c *Client) Query(ctx context.Context, query string) (model.Value, error) {
	// Create context with timeout
	queryCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()

	// Execute query
	result, warnings, err := c.api.Query(queryCtx, query, time.Now())
	if err != nil {
		return nil, fmt.Errorf("prometheus query failed: %w", err)
	}

	// Log warnings if any
	if len(warnings) > 0 {
		c.logger.Debug("Prometheus query warnings", zap.Strings("warnings", warnings))
	}

	return result, nil
}

// QueryRange executes a PromQL range query and returns the result
func (c *Client) QueryRange(
	ctx context.Context, query string, start, end time.Time, step time.Duration,
) (model.Value, error) {
	queryCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()

	r := v1.Range{
		Start: start,
		End:   end,
		Step:  step,
	}

	result, warnings, err := c.api.QueryRange(queryCtx, query, r)
	if err != nil {
		return nil, fmt.Errorf("prometheus range query failed: %w", err)
	}

	if len(warnings) > 0 {
		c.logger.Debug("Prometheus range query warnings", zap.Strings("warnings", warnings))
	}

	return result, nil
}

// IsHealthy checks if the Prometheus endpoint is reachable
func (c *Client) IsHealthy(ctx context.Context) error {
	healthCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()

	// Try to execute a simple query to check connectivity
	_, err := c.Query(healthCtx, "up")
	if err != nil {
		return fmt.Errorf("prometheus health check failed: %w", err)
	}

	return nil
}
