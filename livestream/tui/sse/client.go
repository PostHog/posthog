package sse

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

type Client struct {
	Host       string
	Token      string
	eventType  string
	distinctID string
	geoOnly    bool
	httpClient *http.Client
}

func NewClient(host, token, eventType, distinctID string, geoOnly bool) *Client {
	return &Client{
		Host:       strings.TrimRight(host, "/"),
		Token:      token,
		eventType:  eventType,
		distinctID: distinctID,
		geoOnly:    geoOnly,
		httpClient: &http.Client{Timeout: 0},
	}
}

// PollStatsMsg triggers a stats fetch.
type PollStatsMsg struct {
	SSEClient *Client
	Ctx       context.Context
}

func (c *Client) PollStats(ctx context.Context) tea.Cmd {
	return tea.Tick(1500*time.Millisecond, func(_ time.Time) tea.Msg {
		return PollStatsMsg{SSEClient: c, Ctx: ctx}
	})
}

func FetchStats(p PollStatsMsg) tea.Cmd {
	return func() tea.Msg {
		url := p.SSEClient.Host + "/stats"
		req, err := http.NewRequestWithContext(p.Ctx, "GET", url, nil)
		if err != nil {
			return StatsErrorMsg{Err: err}
		}
		req.Header.Set("Authorization", "Bearer "+p.SSEClient.Token)

		resp, err := p.SSEClient.httpClient.Do(req)
		if err != nil {
			return StatsErrorMsg{Err: err}
		}
		defer resp.Body.Close() //nolint:errcheck

		if resp.StatusCode != http.StatusOK {
			return StatsErrorMsg{Err: fmt.Errorf("stats returned %d", resp.StatusCode)}
		}

		var stats StatsMsg
		if err := json.NewDecoder(resp.Body).Decode(&stats); err != nil {
			return StatsErrorMsg{Err: err}
		}
		return stats
	}
}
