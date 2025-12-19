package core

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"
)

type EnvConfig struct {
	PosthogSecret        string
	EncryptionSaltKeys   string
	Domain               string
	TLSBlock             string
	RegistryURL          string
	PosthogAppTag        string
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

	return &EnvConfig{
		PosthogSecret:        secret,
		EncryptionSaltKeys:   encryptionKey,
		Domain:               domain,
		TLSBlock:             tlsBlock,
		RegistryURL:          registryURL,
		PosthogAppTag:        version,
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

	return nil
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
			result.WriteString(fmt.Sprintf("%s=\"%s\"\n", key, value))
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
