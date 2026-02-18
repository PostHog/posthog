package auth

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"strconv"
	"time"
)

type CallbackResult struct {
	Token    string
	TeamName string
	TeamID   int
	APIHost  string
	Err      error
}

func StartCallbackServer(ctx context.Context) (int, <-chan CallbackResult, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0, nil, fmt.Errorf("failed to start callback server: %w", err)
	}

	port := listener.Addr().(*net.TCPAddr).Port
	resultCh := make(chan CallbackResult, 1)

	mux := http.NewServeMux()
	mux.HandleFunc("/callback", func(w http.ResponseWriter, r *http.Request) {
		token := r.URL.Query().Get("token")
		teamName := r.URL.Query().Get("team_name")
		teamIDStr := r.URL.Query().Get("team_id")
		apiHost := r.URL.Query().Get("api_host")

		if token == "" {
			resultCh <- CallbackResult{Err: fmt.Errorf("no token received")}
			http.Error(w, "Missing token", http.StatusBadRequest)
			return
		}

		teamID, _ := strconv.Atoi(teamIDStr)

		w.Header().Set("Content-Type", "text/html")
		_, _ = fmt.Fprint(w, `<!DOCTYPE html>
<html>
<head><title>PostHog Live</title></head>
<body style="font-family: system-ui, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1d1f27; color: #fff;">
<div style="text-align: center;">
<h1 style="color: #F54E00;">Authorization complete!</h1>
<p>You can close this tab and return to your terminal.</p>
</div>
</body>
</html>`)

		resultCh <- CallbackResult{
			Token:    token,
			TeamName: teamName,
			TeamID:   teamID,
			APIHost:  apiHost,
		}
	})

	server := &http.Server{Handler: mux}

	go func() {
		_ = server.Serve(listener)
	}()

	go func() {
		select {
		case <-ctx.Done():
		case <-time.After(5 * time.Minute):
		}
		_ = server.Shutdown(context.Background())
	}()

	return port, resultCh, nil
}
