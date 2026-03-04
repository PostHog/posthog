//go:build integration

package events

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/redis/rueidis"
)

func IntegrationClusterAddrs() []string {
	if env := os.Getenv("REDIS_CLUSTER_ADDRS"); env != "" {
		return strings.Split(env, ",")
	}
	return []string{"127.0.0.1:7001", "127.0.0.1:7002", "127.0.0.1:7003"}
}

func NewIntegrationTestClient(t *testing.T) rueidis.Client {
	t.Helper()
	client, err := rueidis.NewClient(rueidis.ClientOption{
		InitAddress:  IntegrationClusterAddrs(),
		DisableCache: true,
	})
	if err != nil {
		t.Skipf("cannot create Redis cluster client (cluster not running?): %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := client.Do(ctx, client.B().Ping().Build()).Error(); err != nil {
		client.Close()
		t.Skipf("cannot ping Redis cluster: %v", err)
	}

	t.Cleanup(func() { client.Close() })
	return client
}
