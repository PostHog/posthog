package auth

import (
	"context"
	"net/http"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/spf13/viper"
)

var authorizationClient = &http.Client{
	Timeout: 3 * time.Second,
	CheckRedirect: func(req *http.Request, via []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

func CheckAccess(ctx context.Context, header http.Header) error {
	url := viper.GetString("jwt.authorization_url")
	if url == "" {
		return nil
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
	}
	request.Header.Set("Authorization", header.Get("Authorization"))
	response, err := authorizationClient.Do(request)
	if err != nil {
		return echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNoContent {
		return nil
	}
	if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
		return echo.NewHTTPError(http.StatusUnauthorized, "live stream access denied")
	}
	return echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
}
