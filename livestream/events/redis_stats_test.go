package events

import (
	"context"
	"testing"

	"github.com/redis/rueidis"
	"github.com/redis/rueidis/mock"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.uber.org/mock/gomock"
)

func okResult() rueidis.RedisResult {
	return mock.Result(mock.RedisInt64(1))
}

func TestAddUser_SendsCorrectCommands(t *testing.T) {
	ctrl := gomock.NewController(t)
	client := mock.NewClient(ctrl)
	ctx := context.Background()

	wantKey := "livestream:users:token_a"
	client.EXPECT().
		DoMulti(ctx,
			mock.MatchFn(func(cmd []string) bool {
				return len(cmd) >= 3 && cmd[0] == "ZADD" && cmd[1] == wantKey
			}, "ZADD "+wantKey),
			mock.Match("EXPIRE", wantKey, "60"),
		).
		Return([]rueidis.RedisResult{okResult(), okResult()})

	w := NewStatsInRedisFromClient(client)
	err := w.AddUser(ctx, "token_a", "user1")
	require.NoError(t, err)
}

func TestGetUserCount_ReturnsCount(t *testing.T) {
	tests := []struct {
		name      string
		token     string
		mockCount int64
		wantCount int64
	}{
		{
			name:      "returns count from ZCARD",
			token:     "token_a",
			mockCount: 5,
			wantCount: 5,
		},
		{
			name:      "returns zero for empty set",
			token:     "token_b",
			mockCount: 0,
			wantCount: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ctrl := gomock.NewController(t)
			client := mock.NewClient(ctrl)
			ctx := context.Background()

			key := "livestream:users:" + tt.token
			client.EXPECT().
				DoMulti(ctx,
					mock.MatchFn(func(cmd []string) bool {
						return len(cmd) >= 4 && cmd[0] == "ZREMRANGEBYSCORE" && cmd[1] == key && cmd[2] == "-inf"
					}, "ZREMRANGEBYSCORE "+key),
					mock.Match("ZCARD", key),
				).
				Return([]rueidis.RedisResult{
					okResult(),
					mock.Result(mock.RedisInt64(tt.mockCount)),
				})

			w := NewStatsInRedisFromClient(client)
			count, err := w.GetUserCount(ctx, tt.token)
			require.NoError(t, err)
			assert.Equal(t, tt.wantCount, count)
		})
	}
}

func TestAddKey_PropagatesError(t *testing.T) {
	ctrl := gomock.NewController(t)
	client := mock.NewClient(ctrl)
	ctx := context.Background()

	client.EXPECT().
		DoMulti(ctx, gomock.Any(), gomock.Any()).
		Return([]rueidis.RedisResult{
			mock.ErrorResult(rueidis.ErrClosing),
			okResult(),
		})

	w := NewStatsInRedisFromClient(client)
	err := w.AddUser(ctx, "token_a", "user1")
	require.Error(t, err)
}

func TestGetCount_PropagatesError(t *testing.T) {
	ctrl := gomock.NewController(t)
	client := mock.NewClient(ctrl)
	ctx := context.Background()

	client.EXPECT().
		DoMulti(ctx, gomock.Any(), gomock.Any()).
		Return([]rueidis.RedisResult{
			mock.ErrorResult(rueidis.ErrClosing),
			okResult(),
		})

	w := NewStatsInRedisFromClient(client)
	count, err := w.GetUserCount(ctx, "token_a")
	require.Error(t, err)
	assert.Equal(t, int64(0), count)
}
