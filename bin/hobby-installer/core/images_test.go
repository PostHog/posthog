package core

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const testToken = "anonymous-pull-token"

// fakeRegistry speaks just enough of the registry v2 API: a bearer-token challenge on /v2/,
// a token endpoint, and manifest HEAD requests for the tags it was told exist.
type fakeRegistry struct {
	*httptest.Server
	nodeTags         map[string]bool
	manifestRequests []string
	tokenScopes      []string
}

func newFakeRegistry(t *testing.T, nodeTags ...string) *fakeRegistry {
	t.Helper()
	r := &fakeRegistry{nodeTags: map[string]bool{}}
	for _, tag := range nodeTags {
		r.nodeTags[tag] = true
	}
	r.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		const prefix = "/v2/posthog/posthog-node/manifests/"
		switch {
		case req.URL.Path == "/v2/":
			w.Header().Set("WWW-Authenticate", fmt.Sprintf(`Bearer realm="%s/token",service="fake-registry"`, r.URL))
			w.WriteHeader(http.StatusUnauthorized)
		case req.URL.Path == "/token":
			r.tokenScopes = append(r.tokenScopes, req.URL.Query().Get("scope"))
			_ = json.NewEncoder(w).Encode(map[string]string{"token": testToken})
		case req.Method == http.MethodHead && strings.HasPrefix(req.URL.Path, prefix):
			if req.Header.Get("Authorization") != "Bearer "+testToken {
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			tag := strings.TrimPrefix(req.URL.Path, prefix)
			r.manifestRequests = append(r.manifestRequests, tag)
			if r.nodeTags[tag] {
				w.WriteHeader(http.StatusOK)
			} else {
				w.WriteHeader(http.StatusNotFound)
			}
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(r.Close)
	return r
}

func (r *fakeRegistry) registryURL() string {
	return strings.TrimPrefix(r.URL, "http://") + "/posthog/posthog"
}

func TestResolveNodeTag(t *testing.T) {
	commits := []string{"c0", "c1", "c2", "c3", "c4", "c5"} // newest first, c0 is HEAD
	history := func(appTag string) ([]string, error) {
		for i, c := range commits {
			if c == appTag {
				return commits[i:], nil
			}
		}
		return commits, nil
	}
	cases := []struct {
		name          string
		appTag        string
		pinnedTag     string
		nodeTags      []string
		candidates    func(string) ([]string, error)
		wantTag       string
		wantMatched   bool
		wantManifests []string
	}{
		{
			name:   "commit app tag takes the newest ancestor with an image",
			appTag: "c0", nodeTags: []string{"c3", "c5"}, candidates: history,
			wantTag: "c3", wantMatched: true, wantManifests: []string{"c0", "c1", "c2", "c3"},
		},
		{
			name:   "latest walks from HEAD",
			appTag: "latest", nodeTags: []string{"c3", "c5"}, candidates: history,
			wantTag: "c3", wantMatched: true, wantManifests: []string{"c0", "c1", "c2", "c3"},
		},
		{
			name:   "walk starts at the app commit, not HEAD",
			appTag: "c2", nodeTags: []string{"c1", "c4"}, candidates: history,
			wantTag: "c4", wantMatched: true, wantManifests: []string{"c2", "c3", "c4"},
		},
		{
			name:   "pinned tag skips the registry",
			appTag: "latest", pinnedTag: "pr-123", candidates: history,
			wantTag: "pr-123", wantMatched: true,
		},
		{
			name:   "no image in range falls back to latest",
			appTag: "c0", nodeTags: []string{"c4"}, candidates: func(string) ([]string, error) { return commits[:3], nil },
			wantTag: "latest", wantMatched: false, wantManifests: []string{"c0", "c1", "c2"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			registry := newFakeRegistry(t, tc.nodeTags...)
			res := resolveNodeTag(tc.appTag, tc.pinnedTag, newNodeImageRegistry(registry.registryURL(), registry.Client()), tc.candidates)

			if res.Tag != tc.wantTag || res.Matched() != tc.wantMatched {
				t.Fatalf("got %+v, want tag %q matched %v", res, tc.wantTag, tc.wantMatched)
			}
			if strings.Join(registry.manifestRequests, ",") != strings.Join(tc.wantManifests, ",") {
				t.Fatalf("manifest requests = %v, want %v", registry.manifestRequests, tc.wantManifests)
			}
			if !tc.wantMatched && !strings.Contains(res.Reason, "POSTHOG_NODE_TAG=<tag>") {
				t.Fatalf("fallback reason does not say how to pin the tag: %q", res.Reason)
			}
			if len(tc.wantManifests) > 0 && strings.Join(registry.tokenScopes, ",") != "repository:posthog/posthog-node:pull" {
				t.Fatalf("token scopes = %v, want one pull scope for the node repository", registry.tokenScopes)
			}
		})
	}
}

func TestNewNodeImageRegistryLocatesTheNodeRepository(t *testing.T) {
	cases := []struct {
		registryURL string
		wantBaseURL string
		wantPath    string
	}{
		{"posthog/posthog", "https://registry-1.docker.io", "posthog/posthog-node"},
		{"ghcr.io/posthog/posthog", "https://ghcr.io", "posthog/posthog-node"},
		{"mirror.example.com:5000/images/posthog", "https://mirror.example.com:5000", "images/posthog-node"},
		{"localhost:5000/posthog", "http://localhost:5000", "posthog-node"},
	}
	for _, tc := range cases {
		t.Run(tc.registryURL, func(t *testing.T) {
			r := newNodeImageRegistry(tc.registryURL, http.DefaultClient)
			if r.baseURL != tc.wantBaseURL || r.path != tc.wantPath {
				t.Fatalf("got base %q path %q, want base %q path %q", r.baseURL, r.path, tc.wantBaseURL, tc.wantPath)
			}
			if r.repository != tc.registryURL+"-node" {
				t.Fatalf("repository = %q, want %q", r.repository, tc.registryURL+"-node")
			}
		})
	}
}
