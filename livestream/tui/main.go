package main

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/posthog/posthog/livestream/tui/auth"
	"github.com/posthog/posthog/livestream/tui/debug"
	"github.com/spf13/cobra"
)

func main() {
	var (
		token          string
		host           string
		livestreamHost string
		eventType      string
		distinctID     string
		geoOnly        bool
	)

	rootCmd := &cobra.Command{
		Use:   "posthog-live",
		Short: "PostHog live events TUI",
		Long:  "Stream live PostHog events in your terminal.",
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := debug.Init(); err != nil {
				fmt.Fprintf(os.Stderr, "Warning: could not init debug log: %v\n", err)
			}
			defer debug.Close()

			creds, err := auth.Authenticate(auth.Options{
				Token:          token,
				Host:           host,
				LivestreamHost: livestreamHost,
			})
			if err != nil {
				return fmt.Errorf("authentication failed: %w", err)
			}

			debug.Log("session", "authenticated: host=%s livestream=%s team=%s", creds.Host, creds.LivestreamHost, creds.TeamName)

			fmt.Printf("Connected to %s (team: %s)\n", creds.LivestreamHost, creds.TeamName)
			if path := debug.Path(); path != "" {
				fmt.Printf("Debug log: %s\n", path)
			}

			app := NewApp(creds, eventType, distinctID, geoOnly)
			p := tea.NewProgram(app, tea.WithAltScreen())
			if _, err := p.Run(); err != nil {
				return err
			}
			return nil
		},
	}

	rootCmd.Flags().StringVar(&token, "token", "", "JWT token (for scripting)")
	rootCmd.Flags().StringVar(&host, "host", "", "PostHog app host (default: https://app.posthog.com, use http://localhost:8000 for local dev)")
	rootCmd.Flags().StringVar(&livestreamHost, "livestream-host", "", "Livestream service host override (default: http://localhost:8010 for local dev)")
	rootCmd.Flags().StringVar(&eventType, "event-type", "", "Filter by event type(s), comma-separated")
	rootCmd.Flags().StringVar(&distinctID, "distinct-id", "", "Filter by distinct ID")
	rootCmd.Flags().BoolVar(&geoOnly, "geo", false, "Geo-only mode")

	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
