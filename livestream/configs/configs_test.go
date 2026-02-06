package configs

import (
	"os"
	"testing"

	"github.com/spf13/viper"
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
				_ = os.Setenv("LIVESTREAM_JWT_SECRET", "token")
				_ = os.Setenv("LIVESTREAM_POSTGRES_URL", "pg url")
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

func TestSecurityProtocolDefaults(t *testing.T) {
	tests := []struct {
		name                             string
		securityProtocol                 string
		sessionRecordingSecurityProtocol string
		debug                            bool
		wantMain                         string
		wantSessionRecording             string
	}{
		{
			name:             "debug mode defaults main to PLAINTEXT, session recording to SSL",
			debug:            true,
			wantMain:         "PLAINTEXT",
			wantSessionRecording: "SSL",
		},
		{
			name:             "non-debug defaults both to SSL",
			debug:            false,
			wantMain:         "SSL",
			wantSessionRecording: "SSL",
		},
		{
			name:                             "explicit values are preserved",
			securityProtocol:                 "PLAINTEXT",
			sessionRecordingSecurityProtocol: "PLAINTEXT",
			wantMain:                         "PLAINTEXT",
			wantSessionRecording:             "PLAINTEXT",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			viper.Reset()
			viper.Set("mmdb.path", "mmdb.db")
			viper.Set("kafka.brokers", "localhost:9092")
			viper.Set("kafka.topic", "events")
			viper.Set("kafka.group_id", "test")
			viper.Set("kafka.session_recording_enabled", true)
			viper.Set("debug", tt.debug)

			if tt.securityProtocol != "" {
				viper.Set("kafka.security_protocol", tt.securityProtocol)
			}
			if tt.sessionRecordingSecurityProtocol != "" {
				viper.Set("kafka.session_recording_security_protocol", tt.sessionRecordingSecurityProtocol)
			}

			config, err := LoadConfig()
			assert.NoError(t, err)
			assert.Equal(t, tt.wantMain, config.Kafka.SecurityProtocol)
			assert.Equal(t, tt.wantSessionRecording, config.Kafka.SessionRecordingSecurityProtocol)
		})
	}
}
