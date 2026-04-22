package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

type Config struct {
	Credentials *Credentials `json:"credentials,omitempty"`
	Columns     []Column     `json:"columns,omitempty"`
}

type Credentials struct {
	Host           string    `json:"host"`
	LivestreamHost string    `json:"livestream_host"`
	Token          string    `json:"token"`
	TeamID         int       `json:"team_id"`
	TeamName       string    `json:"team_name"`
	ExpiresAt      time.Time `json:"expires_at"`
}

func (c *Credentials) IsExpired() bool {
	return time.Now().After(c.ExpiresAt)
}

type Column struct {
	Name  string `json:"name"`
	Width int    `json:"width"`
}

func configPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".posthog", "livestream.json"), nil
}

func Load() *Config {
	path, err := configPath()
	if err != nil {
		return &Config{}
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return &Config{}
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return &Config{}
	}
	return &cfg
}

func Save(cfg *Config) error {
	path, err := configPath()
	if err != nil {
		return err
	}

	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}

	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(path, data, 0600)
}
