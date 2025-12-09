package installer

import (
	"fmt"
	"os"
	"time"
)

// EnvConfig holds the configuration for the .env file
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

// Loads existing .env values and preserves them
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

// Updates the .env file for an upgrade, preserving secrets
func UpdateEnvForUpgrade(version string) error {
	existing := LoadExistingEnv()

	// Check if ENCRYPTION_SALT_KEYS exists, add if missing
	if existing["ENCRYPTION_SALT_KEYS"] == "" {
		key, err := GenerateEncryptionKey()
		if err != nil {
			return err
		}
		if err := AppendToEnv("ENCRYPTION_SALT_KEYS", key); err != nil {
			return err
		}
	}

	// Check if SESSION_RECORDING_V2_METADATA_SWITCHOVER exists, add if missing
	if existing["SESSION_RECORDING_V2_METADATA_SWITCHOVER"] == "" {
		if err := AppendToEnv("SESSION_RECORDING_V2_METADATA_SWITCHOVER", time.Now().Format(time.RFC3339)); err != nil {
			return err
		}
	}

	return nil
}

// Checks if the encryption key is in valid format
func ValidateEncryptionKey(key string) bool {
	// Should be 32 hex characters
	if len(key) != 32 {
		return false
	}
	for _, c := range key {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')) {
			return false
		}
	}
	return true
}
