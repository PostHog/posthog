package events

type StatsProvider interface {
	GetUsersOnProduct(token string) int
	GetActiveRecordings(token string) int
}

type statsProvider struct {
	stats        *Stats
	sessionStats *SessionStats
}

func NewStatsProvider(stats *Stats, sessionStats *SessionStats) StatsProvider {
	return &statsProvider{
		stats:        stats,
		sessionStats: sessionStats,
	}
}

func (s *statsProvider) GetUsersOnProduct(token string) int {
	store := s.stats.GetExistingStoreForToken(token)
	if store == nil {
		return 0
	}
	return store.Len()
}

func (s *statsProvider) GetActiveRecordings(token string) int {
	return s.sessionStats.CountForToken(token)
}
