package auth

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/netip"
	"strings"
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

// The geo stream derives its coordinates and country from the event's IP, the same lookup
// that fills every $geoip_* property, so it stays hidden while any of those is.
const (
	ipProperty          = "$ip"
	geoipPropertyPrefix = "$geoip_"
	// Group restrictions the authorize endpoint could not attribute to a group type apply to every type.
	AnyGroupType = "*"
)

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
	if _, restricted := r.GroupProperties[AnyGroupType][key]; restricted {
		return true
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
	if r == nil {
		return false
	}
	for key := range r.EventProperties {
		if key == ipProperty || strings.HasPrefix(key, geoipPropertyPrefix) {
			return true
		}
	}
	return false
}

type authorizationResponse struct {
	IPRestrictions             [][]string          `json:"ip_restrictions"`
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
func CheckAccess(ctx context.Context, viewerRequest *http.Request) (*PropertyRestrictions, error) {
	url := viper.GetString("jwt.authorization_url")
	if url == "" {
		return nil, nil
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
	}
	request.Header.Set("Authorization", viewerRequest.Header.Get("Authorization"))
	// Django answers 204 to a client that does not ask for JSON, so an older service keeps working.
	request.Header.Set("Accept", "application/json")
	request.Header.Set("X-PostHog-Livestream-IP-Policy", "1")
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
		if err := enforceIPRestrictions(viewerRequest, payload.IPRestrictions); err != nil {
			return nil, err
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

var viewerIPExtractor = echo.ExtractIPFromXFFHeader()

func enforceIPRestrictions(request *http.Request, policies [][]string) error {
	if len(policies) == 0 {
		return nil
	}
	viewerIP, err := netip.ParseAddr(viewerIPExtractor(request))
	if err != nil {
		return echo.NewHTTPError(http.StatusUnauthorized, "live stream access denied")
	}
	for _, rules := range policies {
		allowed := len(rules) == 0
		for _, rule := range rules {
			prefix, err := netip.ParsePrefix(rule)
			if err != nil {
				address, addressErr := netip.ParseAddr(rule)
				if addressErr != nil {
					return echo.NewHTTPError(http.StatusServiceUnavailable, "live stream authorization unavailable")
				}
				prefix = netip.PrefixFrom(address, address.BitLen())
			}
			allowed = allowed || prefix.Contains(viewerIP)
		}
		if !allowed {
			return echo.NewHTTPError(http.StatusUnauthorized, "live stream access denied")
		}
	}
	return nil
}
