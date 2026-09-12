package core

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"
)

// auxTagGuidanceComment documents the pinnable auxiliary image tags. It matches
// the block that bin/deploy-hobby and bin/upgrade-hobby write, so an operator
// learns the same knobs whichever installer they used.
const auxTagGuidanceComment = `# Auxiliary service image tags.
# These pin the PostHog-built services that run next to the app.
# Set them to run a reproducible stack that matches a pinned app version.
# When unset, each service tracks its master or latest image.
# Pin a service to the tag that the registry published for your commit:
#   POSTHOG_NODE_TAG        full commit sha  (node services)
#   POSTHOG_LIVESTREAM_TAG  full commit sha  (livestream)
#   POSTHOG_RUST_TAG        sha-<short sha>  (capture, feature-flags, personhog, cymbal, ...)
# The build publishes a tag for a commit only when that commit changes the service.
# Not every app commit has a matching tag, so pick a tag that exists in the registry.
# POSTHOG_RUST_TAG covers several images that build independently, so a usable
# value must exist for all of them. A commit publishes a sha-<short> tag only for
# the Rust images it changed; pin it only to a tag present for every Rust image,
# or leave it on master.`

type EnvConfig struct {
	PosthogSecret        string
	EncryptionSaltKeys   string
	Domain               string
	TLSBlock             string
	RegistryURL          string
	PosthogAppTag        string
	PosthogNodeTag       string
	SessionRecordingDate string
}

func NewEnvConfig(domain, version string) (*EnvConfig, error) {
	secret, err := GenerateSecret()
	if err != nil {
		return nil, fmt.Errorf("failed to generate secret: %w", err)
	}

	encryptionKey, err := GenerateEncryptionKey()
	if err != nil {
		return nil, fmt.Errorf("failed to generate encryption key: %w", err)
	}

	registryURL := os.Getenv("REGISTRY_URL")
	if registryURL == "" {
		registryURL = "posthog/posthog"
	}

	tlsBlock := os.Getenv("TLS_BLOCK")

	nodeTag := os.Getenv("POSTHOG_NODE_TAG")
	if nodeTag == "" {
		nodeTag = "latest"
	}

	return &EnvConfig{
		PosthogSecret:        secret,
		EncryptionSaltKeys:   encryptionKey,
		Domain:               domain,
		TLSBlock:             tlsBlock,
		RegistryURL:          registryURL,
		PosthogAppTag:        version,
		PosthogNodeTag:       nodeTag,
		SessionRecordingDate: time.Now().Format(time.RFC3339),
	}, nil
}

func (c *EnvConfig) WriteEnvFile() error {
	content := fmt.Sprintf(`POSTHOG_SECRET=%s
ENCRYPTION_SALT_KEYS=%s
DOMAIN=%s
TLS_BLOCK=%s
REGISTRY_URL=%s
CADDY_TLS_BLOCK=%s
CADDY_HOST="%s, http://, https://"
POSTHOG_APP_TAG=%s
%s
POSTHOG_NODE_TAG=%s
# POSTHOG_LIVESTREAM_TAG=
# POSTHOG_RUST_TAG=
SESSION_RECORDING_V2_METADATA_SWITCHOVER=%s
`,
		c.PosthogSecret,
		c.EncryptionSaltKeys,
		c.Domain,
		c.TLSBlock,
		c.RegistryURL,
		c.TLSBlock,
		c.Domain,
		c.PosthogAppTag,
		auxTagGuidanceComment,
		c.PosthogNodeTag,
		c.SessionRecordingDate,
	)

	return os.WriteFile(".env", []byte(content), 0600)
}

func LoadExistingEnv() map[string]string {
	values := make(map[string]string)
	keys := []string{
		"POSTHOG_SECRET",
		"ENCRYPTION_SALT_KEYS",
		"DOMAIN",
		"TLS_BLOCK",
		"REGISTRY_URL",
		"POSTHOG_APP_TAG",
		"POSTHOG_NODE_TAG",
		"SESSION_RECORDING_V2_METADATA_SWITCHOVER",
		"SESSION_RECORDING_STORAGE_MIGRATED_TO_SEAWEEDFS",
	}

	for _, key := range keys {
		if val := ReadEnvValue(key); val != "" {
			values[key] = val
		}
	}

	return values
}

func UpdateEnvValue(key, value string) error {
	data, err := os.ReadFile(".env")
	if err != nil {
		return err
	}
	lines := strings.Split(string(data), "\n")
	prefix := key + "="
	found := false
	for i, line := range lines {
		if strings.HasPrefix(line, prefix) {
			lines[i] = prefix + value
			found = true
			break
		}
	}
	if !found {
		lines = append(lines, prefix+value)
	}
	return os.WriteFile(".env", []byte(strings.Join(lines, "\n")), 0600)
}

func UpdateEnvForUpgrade(version string) error {
	existing := LoadExistingEnv()

	if existing["ENCRYPTION_SALT_KEYS"] == "" {
		key, err := GenerateEncryptionKey()
		if err != nil {
			return err
		}
		if err := AppendToEnv("ENCRYPTION_SALT_KEYS", key); err != nil {
			return err
		}
	}

	if existing["SESSION_RECORDING_V2_METADATA_SWITCHOVER"] == "" {
		if err := AppendToEnv("SESSION_RECORDING_V2_METADATA_SWITCHOVER", time.Now().Format(time.RFC3339)); err != nil {
			return err
		}
	}

	if version != "" {
		if err := UpdateEnvValue("POSTHOG_APP_TAG", version); err != nil {
			return err
		}
	}

	if err := AppendAuxTagGuidance(); err != nil {
		return err
	}

	return nil
}

// AppendAuxTagGuidance surfaces the auxiliary image tag knobs on installs whose
// .env predates them. The lines are commented, so the stack keeps tracking
// master/latest until the operator uncomments and sets a tag.
func AppendAuxTagGuidance() error {
	data, err := os.ReadFile(".env")
	if err != nil {
		return err
	}
	if strings.Contains(string(data), "POSTHOG_RUST_TAG") {
		return nil
	}

	f, err := os.OpenFile(".env", os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()

	_, err = fmt.Fprintf(f, "%s\n# POSTHOG_LIVESTREAM_TAG=\n# POSTHOG_RUST_TAG=\n", auxTagGuidanceComment)
	return err
}

func FixEnvQuoting() error {
	data, err := os.ReadFile(".env")
	if err != nil {
		return nil
	}

	var result strings.Builder
	scanner := bufio.NewScanner(strings.NewReader(string(data)))

	for scanner.Scan() {
		line := scanner.Text()

		if strings.TrimSpace(line) == "" || strings.HasPrefix(strings.TrimSpace(line), "#") {
			result.WriteString(line)
			result.WriteString("\n")
			continue
		}

		idx := strings.Index(line, "=")
		if idx == -1 {
			result.WriteString(line)
			result.WriteString("\n")
			continue
		}

		key := strings.TrimSpace(line[:idx])
		value := strings.TrimSpace(line[idx+1:])

		if (strings.HasPrefix(value, "\"") && strings.HasSuffix(value, "\"")) ||
			(strings.HasPrefix(value, "'") && strings.HasSuffix(value, "'")) {
			result.WriteString(line)
			result.WriteString("\n")
			continue
		}

		needsQuote := strings.ContainsAny(value, " ,") || strings.Contains(value, "://")
		if needsQuote {
			value = strings.ReplaceAll(value, "\"", "\\\"")
			fmt.Fprintf(&result, "%s=\"%s\"\n", key, value)
		} else {
			result.WriteString(line)
			result.WriteString("\n")
		}
	}

	return os.WriteFile(".env", []byte(result.String()), 0600)
}

func ValidateEnvForUpgrade() error {
	required := []string{"POSTHOG_SECRET", "DOMAIN"}
	for _, key := range required {
		if ReadEnvValue(key) == "" {
			return fmt.Errorf("missing required env var: %s", key)
		}
	}

	encKey := ReadEnvValue("ENCRYPTION_SALT_KEYS")
	if encKey != "" {
		if !regexp.MustCompile(`^[A-Za-z0-9_-]{32}$`).MatchString(encKey) {
			return fmt.Errorf("ENCRYPTION_SALT_KEYS is not in correct format")
		}
	}

	return nil
}

func GetExistingDomain() string {
	return ReadEnvValue("DOMAIN")
}
