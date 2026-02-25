package events

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now(_ context.Context) (time.Time, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t, nil
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

func setupMiniredis(t *testing.T) (*RedisStatsWriter, *fakeClock) {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	clk := &fakeClock{t: time.Now()}
	w := NewRedisStatsWriterFromClient(client)
	w.nowFunc = clk.now
	return w, clk
}

func TestAddUser_GetUserCount(t *testing.T) {
	tests := []struct {
		name      string
		users     []struct{ token, distinctID string }
		queryTkn  string
		wantCount int64
	}{
		{
			name: "single user counted once",
			users: []struct{ token, distinctID string }{
				{"token_a", "user1"},
			},
			queryTkn:  "token_a",
			wantCount: 1,
		},
		{
			name: "duplicate distinct ID is deduplicated",
			users: []struct{ token, distinctID string }{
				{"token_a", "user1"},
				{"token_a", "user1"},
				{"token_a", "user1"},
			},
			queryTkn:  "token_a",
			wantCount: 1,
		},
		{
			name: "multiple distinct users counted",
			users: []struct{ token, distinctID string }{
				{"token_a", "user1"},
				{"token_a", "user2"},
				{"token_a", "user3"},
			},
			queryTkn:  "token_a",
			wantCount: 3,
		},
		{
			name:      "unknown token returns zero",
			users:     nil,
			queryTkn:  "token_unknown",
			wantCount: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w, _ := setupMiniredis(t)
			ctx := context.Background()

			for _, u := range tt.users {
				require.NoError(t, w.AddUser(ctx, u.token, u.distinctID))
			}

			count, err := w.GetUserCount(ctx, tt.queryTkn)
			require.NoError(t, err)
			assert.Equal(t, tt.wantCount, count)
		})
	}
}

func TestAddSession_GetSessionCount(t *testing.T) {
	tests := []struct {
		name      string
		sessions  []struct{ token, sessionID string }
		queryTkn  string
		wantCount int64
	}{
		{
			name: "single session counted",
			sessions: []struct{ token, sessionID string }{
				{"token_a", "session_1"},
			},
			queryTkn:  "token_a",
			wantCount: 1,
		},
		{
			name: "duplicate session ID is deduplicated",
			sessions: []struct{ token, sessionID string }{
				{"token_a", "session_1"},
				{"token_a", "session_1"},
			},
			queryTkn:  "token_a",
			wantCount: 1,
		},
		{
			name: "multiple sessions counted",
			sessions: []struct{ token, sessionID string }{
				{"token_a", "session_1"},
				{"token_a", "session_2"},
				{"token_a", "session_3"},
			},
			queryTkn:  "token_a",
			wantCount: 3,
		},
		{
			name:      "unknown token returns zero",
			sessions:  nil,
			queryTkn:  "token_unknown",
			wantCount: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w, _ := setupMiniredis(t)
			ctx := context.Background()

			for _, s := range tt.sessions {
				require.NoError(t, w.AddSession(ctx, s.token, s.sessionID))
			}

			count, err := w.GetSessionCount(ctx, tt.queryTkn)
			require.NoError(t, err)
			assert.Equal(t, tt.wantCount, count)
		})
	}
}

func TestSessionExpiry(t *testing.T) {
	w, clk := setupMiniredis(t)
	ctx := context.Background()

	require.NoError(t, w.AddSession(ctx, "token_a", "session_1"))
	require.NoError(t, w.AddSession(ctx, "token_a", "session_2"))

	count, err := w.GetSessionCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(2), count)

	clk.advance(6 * time.Minute)

	count, err = w.GetSessionCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(0), count)
}

func TestUserExpiry(t *testing.T) {
	w, clk := setupMiniredis(t)
	ctx := context.Background()

	require.NoError(t, w.AddUser(ctx, "token_a", "user1"))
	require.NoError(t, w.AddUser(ctx, "token_a", "user2"))

	count, err := w.GetUserCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(2), count)

	clk.advance(userKeyTTL + time.Second)

	count, err = w.GetUserCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(0), count)
}

func TestUserNaturalDecay(t *testing.T) {
	w, clk := setupMiniredis(t)
	ctx := context.Background()

	require.NoError(t, w.AddUser(ctx, "token_a", "user1"))

	clk.advance(30 * time.Second)

	require.NoError(t, w.AddUser(ctx, "token_a", "user2"))

	count, err := w.GetUserCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(2), count)

	clk.advance(40 * time.Second)

	count, err = w.GetUserCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(1), count, "only user2 should remain after user1 ages out")
}

func TestCrossTokenIsolation(t *testing.T) {
	w, _ := setupMiniredis(t)
	ctx := context.Background()

	require.NoError(t, w.AddUser(ctx, "token_a", "user1"))
	require.NoError(t, w.AddUser(ctx, "token_a", "user2"))
	require.NoError(t, w.AddUser(ctx, "token_b", "user3"))

	require.NoError(t, w.AddSession(ctx, "token_a", "session_1"))
	require.NoError(t, w.AddSession(ctx, "token_b", "session_2"))
	require.NoError(t, w.AddSession(ctx, "token_b", "session_3"))

	countA, err := w.GetUserCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(2), countA)

	countB, err := w.GetUserCount(ctx, "token_b")
	require.NoError(t, err)
	assert.Equal(t, int64(1), countB)

	sessA, err := w.GetSessionCount(ctx, "token_a")
	require.NoError(t, err)
	assert.Equal(t, int64(1), sessA)

	sessB, err := w.GetSessionCount(ctx, "token_b")
	require.NoError(t, err)
	assert.Equal(t, int64(2), sessB)
}
