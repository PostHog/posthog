//go:build integration

package events

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRedisClusterSmoke(t *testing.T) {
	client := NewIntegrationTestClient(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	t.Run("set and get round-trip", func(t *testing.T) {
		key := "integration-test:smoke"
		require.NoError(t, client.Do(ctx, client.B().Set().Key(key).Value("hello").Ex(10*time.Second).Build()).Error())

		val, err := client.Do(ctx, client.B().Get().Key(key).Build()).ToString()
		require.NoError(t, err)
		assert.Equal(t, "hello", val)
	})

	t.Run("cluster has expected node count", func(t *testing.T) {
		info, err := client.Do(ctx, client.B().ClusterInfo().Build()).ToString()
		require.NoError(t, err)
		assert.Contains(t, info, "cluster_state:ok")
		assert.Contains(t, info, "cluster_known_nodes:3")
	})
}
