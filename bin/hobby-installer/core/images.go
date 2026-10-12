package core

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
)

// Mirrors bin/helpers/resolve-hobby-node-tag.sh, which bin/deploy-hobby and bin/upgrade-hobby
// use. Keep the two in step when the pairing rule changes.

const nodeTagMaxCommits = 100

var commitHashPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)

// Reason is set when Tag is the "latest" fallback, so the caller can warn before the stack starts.
type NodeTagResolution struct {
	Tag    string
	Reason string
}

func (r NodeTagResolution) Matched() bool {
	return r.Reason == ""
}

// ResolveNodeImageTag picks the posthog-node image built from the same source as the app image.
// A Node image is only built when a master commit touches Node code, so the match for app commit
// X is the newest first-parent ancestor of X that has one. Walking the checkout's history and
// asking the registry finds it without a copy of the workflow's path filter, which would drift.
// POSTHOG_NODE_TAG in the environment pins the tag and skips the walk.
func ResolveNodeImageTag(appTag string) NodeTagResolution {
	registryURL := os.Getenv("REGISTRY_URL")
	if registryURL == "" {
		registryURL = "posthog/posthog"
	}
	registry := newNodeImageRegistry(registryURL, &http.Client{Timeout: 30 * time.Second})
	return resolveNodeTag(appTag, os.Getenv("POSTHOG_NODE_TAG"), registry, nodeImageCandidates)
}

func resolveNodeTag(appTag, pinnedTag string, registry *nodeImageRegistry, candidates func(appTag string) ([]string, error)) NodeTagResolution {
	logger := GetLogger()
	if pinnedTag != "" {
		logger.WriteString(fmt.Sprintf("Using the Node image tag you set: %s:%s\n", registry.repository, pinnedTag))
		return NodeTagResolution{Tag: pinnedTag}
	}

	fallBack := func(detail string) NodeTagResolution {
		reason := fmt.Sprintf("No posthog-node image matches the PostHog app image %s:%s.\n%s\n"+
			"Using %s:latest instead. It may run against a database schema it does not expect.\n"+
			"To use a specific Node image, run the install or upgrade again with POSTHOG_NODE_TAG=<tag> set in your shell.",
			registry.appRepository, appTag, detail, registry.repository)
		logger.WriteString("⚠ " + reason + "\n")
		return NodeTagResolution{Tag: "latest", Reason: reason}
	}

	commits, err := candidates(appTag)
	if err != nil || len(commits) == 0 {
		return fallBack(fmt.Sprintf("Could not read the commit history for %s: %v", appTag, err))
	}

	logger.WriteString(fmt.Sprintf("Looking for a %s image built from commit %s or an earlier one...\n", registry.repository, shortCommit(commits[0])))
	for _, commit := range commits {
		found, err := registry.hasTag(commit)
		if err != nil {
			return fallBack(fmt.Sprintf("Could not check %s:%s: %v", registry.repository, shortCommit(commit), err))
		}
		if found {
			logger.WriteString(fmt.Sprintf("Found %s:%s\n", registry.repository, shortCommit(commit)))
			return NodeTagResolution{Tag: commit}
		}
	}
	return fallBack(fmt.Sprintf("Checked the %d commits from %s back and found no Node image for any of them in %s.",
		len(commits), shortCommit(commits[0]), registry.repository))
}

// Any app tag that is not a commit hash starts at HEAD, which the checkout step put on that tag.
func nodeImageCandidates(appTag string) ([]string, error) {
	start := "HEAD"
	if commitHashPattern.MatchString(appTag) {
		start = appTag
	}
	out, err := runCmdDir("posthog", "git", "rev-list", "--first-parent", fmt.Sprintf("--max-count=%d", nodeTagMaxCommits), start)
	if err != nil {
		return nil, err
	}
	return strings.Fields(out), nil
}

func shortCommit(commit string) string {
	if len(commit) > 10 {
		return commit[:10]
	}
	return commit
}

// nodeImageRegistry answers "does this tag exist" with manifest HEAD requests, which Docker
// Hub does not count toward its pull limits. It fetches an anonymous pull token the way
// `docker pull` does, from the realm the registry names in its WWW-Authenticate challenge.
type nodeImageRegistry struct {
	client        *http.Client
	appRepository string
	repository    string
	baseURL       string
	path          string
	token         string
	tokenFetched  bool
}

func newNodeImageRegistry(registryURL string, client *http.Client) *nodeImageRegistry {
	r := &nodeImageRegistry{client: client, appRepository: registryURL, repository: registryURL + "-node"}

	// A repository with no registry host, like posthog/posthog, lives on Docker Hub. Docker treats
	// the first path segment as a host only when it has a dot or a port, or is localhost.
	first, rest, hasSlash := strings.Cut(registryURL, "/")
	if hasSlash && (strings.Contains(first, ".") || strings.Contains(first, ":") || first == "localhost") {
		r.baseURL = "https://" + first
		if strings.HasPrefix(first, "localhost") || strings.HasPrefix(first, "127.0.0.1") {
			r.baseURL = "http://" + first
		}
		r.path = rest + "-node"
	} else {
		r.baseURL = "https://registry-1.docker.io"
		r.path = r.repository
		if !hasSlash {
			r.path = "library/" + r.path
		}
	}
	return r
}

func (r *nodeImageRegistry) hasTag(tag string) (bool, error) {
	if err := r.ensureToken(); err != nil {
		return false, err
	}
	req, err := http.NewRequest(http.MethodHead, fmt.Sprintf("%s/v2/%s/manifests/%s", r.baseURL, r.path, tag), nil)
	if err != nil {
		return false, err
	}
	req.Header.Set("Accept", "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json")
	if r.token != "" {
		req.Header.Set("Authorization", "Bearer "+r.token)
	}
	resp, err := r.client.Do(req)
	if err != nil {
		return false, err
	}
	_ = resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
		return true, nil
	case http.StatusNotFound:
		return false, nil
	default:
		return false, fmt.Errorf("registry answered %d", resp.StatusCode)
	}
}

var challengeField = regexp.MustCompile(`(\w+)="([^"]*)"`)

func (r *nodeImageRegistry) ensureToken() error {
	if r.tokenFetched {
		return nil
	}
	resp, err := r.client.Get(r.baseURL + "/v2/")
	if err != nil {
		return err
	}
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		r.tokenFetched = true
		return nil
	}

	fields := map[string]string{}
	for _, m := range challengeField.FindAllStringSubmatch(resp.Header.Get("WWW-Authenticate"), -1) {
		fields[m[1]] = m[2]
	}
	realm := fields["realm"]
	if realm == "" {
		r.tokenFetched = true
		return nil
	}
	query := url.Values{"service": {fields["service"]}, "scope": {"repository:" + r.path + ":pull"}}
	tokenResp, err := r.client.Get(realm + "?" + query.Encode())
	if err != nil {
		return err
	}
	defer func() { _ = tokenResp.Body.Close() }()
	body, err := io.ReadAll(tokenResp.Body)
	if err != nil {
		return err
	}
	var issued struct {
		Token       string `json:"token"`
		AccessToken string `json:"access_token"`
	}
	if err := json.Unmarshal(body, &issued); err != nil {
		return fmt.Errorf("token endpoint %s answered %d", realm, tokenResp.StatusCode)
	}
	r.token = issued.Token
	if r.token == "" {
		r.token = issued.AccessToken
	}
	if r.token == "" {
		return fmt.Errorf("token endpoint %s issued no pull token", realm)
	}
	r.tokenFetched = true
	return nil
}
