package auth

import (
	"context"
	"fmt"
	"time"

	"github.com/pkg/browser"
	"github.com/posthog/posthog/livestream/tui/config"
)

type Options struct {
	Token          string
	Host           string
	LivestreamHost string
}

func Authenticate(opts Options) (*config.Credentials, error) {
	host := opts.Host
	if host == "" {
		host = "https://app.posthog.com"
	}

	// Priority 1: direct token flag
	if opts.Token != "" {
		livestreamHost := opts.LivestreamHost
		if livestreamHost == "" {
			livestreamHost = DeriveStreamHost(host)
		}
		return &config.Credentials{
			Host:           host,
			LivestreamHost: livestreamHost,
			Token:          opts.Token,
			ExpiresAt:      time.Now().Add(7 * 24 * time.Hour),
		}, nil
	}

	// Priority 2: cached credentials
	cfg := config.Load()
	if cfg.Credentials != nil && !cfg.Credentials.IsExpired() {
		creds := cfg.Credentials
		if opts.LivestreamHost != "" {
			creds.LivestreamHost = opts.LivestreamHost
		}
		if opts.Host != "" {
			creds.Host = opts.Host
		}
		return creds, nil
	}

	// Priority 3: browser flow
	return browserFlow(host, opts.LivestreamHost)
}

func browserFlow(host, livestreamHostOverride string) (*config.Credentials, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	port, resultCh, err := StartCallbackServer(ctx)
	if err != nil {
		return nil, err
	}

	url := fmt.Sprintf("%s/cli/live?port=%d", host, port)
	fmt.Printf("Opening browser to authorize: %s\n", url)
	if err := browser.OpenURL(url); err != nil {
		fmt.Printf("Could not open browser automatically.\nPlease open this URL manually:\n  %s\n", url)
	}

	fmt.Println("Waiting for authorization...")

	select {
	case result := <-resultCh:
		if result.Err != nil {
			return nil, result.Err
		}

		// Use the actual host the browser landed on (us/eu) to derive livestream host
		actualHost := result.APIHost
		if actualHost == "" {
			actualHost = host
		}

		livestreamHost := livestreamHostOverride
		if livestreamHost == "" {
			livestreamHost = DeriveStreamHost(actualHost)
		}

		creds := &config.Credentials{
			Host:           actualHost,
			LivestreamHost: livestreamHost,
			Token:          result.Token,
			TeamID:         result.TeamID,
			TeamName:       result.TeamName,
			ExpiresAt:      time.Now().Add(7 * 24 * time.Hour),
		}

		cfg := config.Load()
		cfg.Credentials = creds
		if err := config.Save(cfg); err != nil {
			fmt.Printf("Warning: could not save credentials: %v\n", err)
		}

		return creds, nil

	case <-ctx.Done():
		return nil, fmt.Errorf("authorization timed out")
	}
}
