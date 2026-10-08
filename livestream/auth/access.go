package auth

import (
	"context"
	"encoding/json"
	"io"
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

// A nil *PropertyRestrictions restricts nothing, so callers never special-case a user without rules.
type PropertyRestrictions struct {
	EventProperties  map[string]struct{}
	PersonProperties map[string]struct{}
}

func (r *PropertyRestrictions) RestrictsEventProperty(key string) bool {
	if r == nil {
		return false
	}
	_, restricted := r.EventProperties[key]
	return restricted
}

func (r *PropertyRestrictions) RestrictsPersonProperty(key string) bool {
	if r == nil {
		return false
	}
	_, restricted := r.PersonProperties[key]
	return restricted
}

func (r *PropertyRestrictions) HasPersonRestrictions() bool {
	return r != nil && len(r.PersonProperties) > 0
}

type authorizationResponse struct {
	RestrictedEventProperties  []string `json:"restricted_event_properties"`
	RestrictedPersonProperties []string `json:"restricted_person_properties"`
}

func toSet(keys []string) map[string]struct{} {
	if len(keys) == 0 {
		return nil
	}
	set := make(map[string]struct{}, len(keys))
	for _, key := range keys {
		set[key] = struct{}{}
	}
	return set
}

// Fails closed: anything other than an explicit allow or refusal is reported as unavailable.
func CheckAccess(ctx context.Context, header http.Header) (*PropertyRestrictions, error) {
	url := viper.GetString("jwt.authorization_url")
	if url == "" {
		return nil, nil
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
	}
	request.Header.Set("Authorization", header.Get("Authorization"))
	response, err := authorizationClient.Do(request)
	if err != nil {
		return nil, echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
	}
	defer func() { _ = response.Body.Close() }()
	switch response.StatusCode {
	case http.StatusNoContent:
		// Django builds that predate the restriction payload still answer 204.
		return nil, nil
	case http.StatusOK:
		var payload authorizationResponse
		if err := json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(&payload); err != nil {
			return nil, echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
		}
		if len(payload.RestrictedEventProperties) == 0 && len(payload.RestrictedPersonProperties) == 0 {
			return nil, nil
		}
		return &PropertyRestrictions{
			EventProperties:  toSet(payload.RestrictedEventProperties),
			PersonProperties: toSet(payload.RestrictedPersonProperties),
		}, nil
	case http.StatusUnauthorized, http.StatusForbidden:
		return nil, echo.NewHTTPError(http.StatusUnauthorized, "live stream access denied")
	default:
		return nil, echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
	}
}
