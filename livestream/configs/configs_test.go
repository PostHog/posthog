package configs

import (
	"github.com/spf13/viper"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestLoadConfig(t *testing.T) {
	tests := []struct {
		name    string
		setup   func()
		want    *Config
		wantErr bool
	}{
		{
			name: "load all config values",
			setup: func() {
				// Values already set in setupTestConfig
				os.Setenv("LIVESTREAM_JWT_SECRET", "token")
				os.Setenv("LIVESTREAM_POSTGRES_URL", "pg url")
			},
			want: &Config{
				Debug:            true,
				MMDB:             MMDBConfig{Path: "mmdb.db"},
				Parallelism:      7,
				CORSAllowOrigins: []string{"https://example.com", "https://sub.example.com"},
				Kafka: KafkaConfig{
					Brokers:                          "localhost:9092,localhost:9093",
					Topic:                            "topic",
					SecurityProtocol:                 "PLAINTEXT",
					SessionRecordingEnabled:          true,
					SessionRecordingTopic:            "session_recording_snapshot_item_events",
					SessionRecordingBrokers:          "localhost:9092,localhost:9093",
					SessionRecordingSecurityProtocol: "SSL",
					GroupID:                          "livestream-dev",
				},
				Postgres: PostgresConfig{
					URL: "pg url",
				},
				JWT: JWTConfig{
					Secret: "token",
				},
				SessionRecording: SessionRecordingConfig{
					MaxLRUEntries: 2_000_000_000,
				},
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.setup()
			InitConfigs("configs.example", ".")
			got, err := LoadConfig()
			if tt.wantErr {
				assert.Error(t, err)
				return
			}
			assert.NoError(t, err)
			assert.Equal(t, tt.want, got)
			assert.Equal(t, tt.want.Postgres.URL, viper.GetString("postgres.url"))
			assert.Equal(t, tt.want.JWT.Secret, viper.GetString("jwt.secret"))
		})
	}
}
