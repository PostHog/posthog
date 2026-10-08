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
	// Keyed by group type name, the value `$group_type` carries on a $groupidentify event.
	GroupProperties map[string]map[string]struct{}
}

// The geo stream derives its coordinates and country from the event's IP, so it stays
// hidden while any of the properties that would carry those values is.
var geoSourceProperties = []string{"$ip", "$geoip_latitude", "$geoip_longitude", "$geoip_country_code"}

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

func (r *PropertyRestrictions) HasGroupRestrictions() bool {
	return r != nil && len(r.GroupProperties) > 0
}

// RestrictsGroupProperty reports whether key is hidden for groupType. An empty groupType
// means the type is unknown, so the key is hidden if any group type hides it.
func (r *PropertyRestrictions) RestrictsGroupProperty(groupType, key string) bool {
	if r == nil {
		return false
	}
	if groupType != "" {
		_, restricted := r.GroupProperties[groupType][key]
		return restricted
	}
	for _, keys := range r.GroupProperties {
		if _, restricted := keys[key]; restricted {
			return true
		}
	}
	return false
}

func (r *PropertyRestrictions) RestrictsGeo() bool {
	for _, key := range geoSourceProperties {
		if r.RestrictsEventProperty(key) {
			return true
		}
	}
	return false
}

type authorizationResponse struct {
	RestrictedEventProperties  []string            `json:"restricted_event_properties"`
	RestrictedPersonProperties []string            `json:"restricted_person_properties"`
	RestrictedGroupProperties  map[string][]string `json:"restricted_group_properties"`
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
	// Django answers 204 to a client that does not ask for JSON, so an older service keeps working.
	request.Header.Set("Accept", "application/json")
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
		var groups map[string]map[string]struct{}
		for groupType, keys := range payload.RestrictedGroupProperties {
			if set := toSet(keys); set != nil {
				if groups == nil {
					groups = make(map[string]map[string]struct{})
				}
				groups[groupType] = set
			}
		}
		if len(payload.RestrictedEventProperties) == 0 && len(payload.RestrictedPersonProperties) == 0 && groups == nil {
			return nil, nil
		}
		return &PropertyRestrictions{
			EventProperties:  toSet(payload.RestrictedEventProperties),
			PersonProperties: toSet(payload.RestrictedPersonProperties),
			GroupProperties:  groups,
		}, nil
	case http.StatusUnauthorized, http.StatusForbidden:
		return nil, echo.NewHTTPError(http.StatusUnauthorized, "live stream access denied")
	default:
		return nil, echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
	}
}
