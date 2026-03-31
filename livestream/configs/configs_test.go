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
				_ = os.Setenv("LIVESTREAM_JWT_SECRET", "token")
				_ = os.Setenv("LIVESTREAM_POSTGRES_URL", "pg url")
			},
			want: &Config{
				Debug:            true,
				MMDB:             MMDBConfig{Path: "mmdb.db"},
				Parallelism:      7,
				CORSAllowOrigins: []string{"https://example.com", "https://sub.example.com"},
				Consumers: ConsumersConfig{
					Event: ConsumerConfig{
						Enabled:          true,
						Brokers:          "localhost:9092,localhost:9093",
						Topic:            "events_topic",
						SecurityProtocol: "PLAINTEXT",
						GroupID:          "livestream-dev",
					},
					SessionRecording: ConsumerConfig{
						Enabled:          true,
						Brokers:          "localhost:9092,localhost:9093",
						Topic:            "session_recording_snapshot_item_events",
						SecurityProtocol: "SSL",
						GroupID:          "livestream-dev-session-recordings",
					},
					Notification: ConsumerConfig{
						Brokers:          "localhost:9092,localhost:9093",
						Topic:            "notification_events",
						SecurityProtocol: "PLAINTEXT",
						GroupID:          "livestream-dev-notifications",
					},
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
				Redis: RedisConfig{
					FlushIntervalMs:   500,
					PublishBufferSize: 10000,
					PublishWorkers:    256,
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
