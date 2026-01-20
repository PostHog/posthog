package events

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestStatsProvider_GetUsersOnProduct(t *testing.T) {
	t.Run("returns 0 for unknown token", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		assert.Equal(t, 0, provider.GetUsersOnProduct("unknown-token"))
	})

	t.Run("returns 0 for empty token", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		assert.Equal(t, 0, provider.GetUsersOnProduct(""))
	})

	t.Run("returns correct count for token with users", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		stats.GetStoreForToken("team-a").Add("user1", NoSpaceType{})
		stats.GetStoreForToken("team-a").Add("user2", NoSpaceType{})
		stats.GetStoreForToken("team-a").Add("user3", NoSpaceType{})

		assert.Equal(t, 3, provider.GetUsersOnProduct("team-a"))
	})

	t.Run("tokens are isolated from each other", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		stats.GetStoreForToken("team-a").Add("user1", NoSpaceType{})
		stats.GetStoreForToken("team-a").Add("user2", NoSpaceType{})
		stats.GetStoreForToken("team-b").Add("user3", NoSpaceType{})

		assert.Equal(t, 2, provider.GetUsersOnProduct("team-a"))
		assert.Equal(t, 1, provider.GetUsersOnProduct("team-b"))
		assert.Equal(t, 0, provider.GetUsersOnProduct("team-c"))
	})

	t.Run("same user counted once per token", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		stats.GetStoreForToken("team-a").Add("user1", NoSpaceType{})
		stats.GetStoreForToken("team-a").Add("user1", NoSpaceType{})
		stats.GetStoreForToken("team-a").Add("user1", NoSpaceType{})

		assert.Equal(t, 1, provider.GetUsersOnProduct("team-a"))
	})
}

func TestStatsProvider_GetActiveRecordings(t *testing.T) {
	t.Run("returns 0 for unknown token", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		assert.Equal(t, 0, provider.GetActiveRecordings("unknown-token"))
	})

	t.Run("returns 0 for empty token", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		assert.Equal(t, 0, provider.GetActiveRecordings(""))
	})

	t.Run("returns correct count for token with recordings", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		sessionStats.Add("team-a", "session1")
		sessionStats.Add("team-a", "session2")
		sessionStats.Add("team-a", "session3")

		assert.Equal(t, 3, provider.GetActiveRecordings("team-a"))
	})

	t.Run("tokens are isolated from each other", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		sessionStats.Add("team-a", "session1")
		sessionStats.Add("team-a", "session2")
		sessionStats.Add("team-b", "session3")

		assert.Equal(t, 2, provider.GetActiveRecordings("team-a"))
		assert.Equal(t, 1, provider.GetActiveRecordings("team-b"))
		assert.Equal(t, 0, provider.GetActiveRecordings("team-c"))
	})

	t.Run("same session counted once per token", func(t *testing.T) {
		stats := NewStatsKeeper()
		sessionStats := NewSessionStatsKeeper(0, 0)
		provider := NewStatsProvider(stats, sessionStats)

		sessionStats.Add("team-a", "session1")
		sessionStats.Add("team-a", "session1")
		sessionStats.Add("team-a", "session1")

		assert.Equal(t, 1, provider.GetActiveRecordings("team-a"))
	})
}
