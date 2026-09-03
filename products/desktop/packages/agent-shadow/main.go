package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

type config struct {
	BootID       string
	HealthURL    string
	PollInterval time.Duration
	Timeout      time.Duration
}

type healthResponse struct {
	HasSession bool         `json:"hasSession"`
	Readiness  string       `json:"readiness"`
	Boot       bootSnapshot `json:"boot"`
}

type bootSnapshot struct {
	ContractVersion int            `json:"contractVersion"`
	BootID          string         `json:"bootId"`
	TotalMS         int            `json:"totalMs"`
	PhasesMS        map[string]int `json:"phasesMs"`
}

type shadowResult struct {
	ContractVersion int            `json:"contractVersion"`
	BootID          string         `json:"bootId"`
	Outcome         string         `json:"outcome"`
	ObservedReadyMS int            `json:"observedReadyMs"`
	ProductionMS    int            `json:"productionReadyMs"`
	PhasesMS        map[string]int `json:"phasesMs,omitempty"`
	FailureClass    string         `json:"failureClass,omitempty"`
}

func main() {
	var cfg config
	flag.StringVar(&cfg.BootID, "boot-id", "", "task run identifier used to join production and shadow observations")
	flag.StringVar(&cfg.HealthURL, "health-url", "http://127.0.0.1:8080/health", "production agent-server health URL")
	flag.DurationVar(&cfg.PollInterval, "poll-interval", 100*time.Millisecond, "health observation interval")
	flag.DurationVar(&cfg.Timeout, "timeout", 5*time.Minute, "maximum observation duration")
	flag.Parse()

	if cfg.BootID == "" {
		fmt.Fprintln(os.Stderr, "--boot-id is required")
		os.Exit(2)
	}
	if cfg.PollInterval <= 0 {
		fmt.Fprintln(os.Stderr, "--poll-interval must be positive")
		os.Exit(2)
	}

	ctx, cancel := context.WithTimeout(context.Background(), cfg.Timeout)
	defer cancel()
	result := observe(ctx, http.DefaultClient, cfg, time.Now)
	if err := json.NewEncoder(os.Stdout).Encode(result); err != nil {
		fmt.Fprintln(os.Stderr, "failed to encode shadow result")
		os.Exit(1)
	}
	if result.Outcome != "ready" {
		os.Exit(1)
	}
}

type httpDoer interface {
	Do(*http.Request) (*http.Response, error)
}

func observe(ctx context.Context, client httpDoer, cfg config, now func() time.Time) shadowResult {
	startedAt := now()
	ticker := time.NewTicker(cfg.PollInterval)
	defer ticker.Stop()

	for {
		health, err := readHealth(ctx, client, cfg.HealthURL)
		if err == nil && health.HasSession && health.Readiness == "ready" && health.Boot.BootID == cfg.BootID {
			if health.Boot.ContractVersion != 1 {
				return failed(cfg.BootID, startedAt, now(), "unsupported_contract")
			}
			return shadowResult{
				ContractVersion: 1,
				BootID:          cfg.BootID,
				Outcome:         "ready",
				ObservedReadyMS: elapsedMS(startedAt, now()),
				ProductionMS:    health.Boot.TotalMS,
				PhasesMS:        allowlistedPhases(health.Boot.PhasesMS),
			}
		}

		select {
		case <-ctx.Done():
			return failed(cfg.BootID, startedAt, now(), "timeout")
		case <-ticker.C:
		}
	}
}

func readHealth(ctx context.Context, client httpDoer, url string) (healthResponse, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return healthResponse{}, err
	}
	response, err := client.Do(request)
	if err != nil {
		return healthResponse{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, response.Body)
		return healthResponse{}, errors.New("health endpoint unavailable")
	}
	var health healthResponse
	if err := json.NewDecoder(io.LimitReader(response.Body, 64<<10)).Decode(&health); err != nil {
		return healthResponse{}, err
	}
	return health, nil
}

func allowlistedPhases(phases map[string]int) map[string]int {
	allowed := map[string]bool{
		"context_fetch":        true,
		"acp_initialize":       true,
		"repository_ready":     true,
		"session_dependencies": true,
		"session_create":       true,
	}
	result := make(map[string]int, len(allowed))
	for phase, duration := range phases {
		if allowed[phase] && duration >= 0 {
			result[phase] = duration
		}
	}
	return result
}

func failed(bootID string, startedAt, endedAt time.Time, class string) shadowResult {
	return shadowResult{
		ContractVersion: 1,
		BootID:          bootID,
		Outcome:         "failed",
		ObservedReadyMS: elapsedMS(startedAt, endedAt),
		FailureClass:    class,
	}
}

func elapsedMS(startedAt, endedAt time.Time) int {
	return max(0, int(endedAt.Sub(startedAt)/time.Millisecond))
}
