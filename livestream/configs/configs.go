package configs

import (
	"errors"
	"log"
	"strings"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"
)

type MMDBConfig struct {
	Path string
}

type PostgresConfig struct {
	URL string
}

type JWTConfig struct {
	Secret string
}

type SessionRecordingConfig struct {
	MaxLRUEntries int `mapstructure:"max_lru_entries"`
}

type Config struct {
	Debug            bool `mapstructure:"debug"`
	MMDB             MMDBConfig
	Kafka            KafkaConfig
	Parallelism      int      `mapstructure:"parallelism"`
	CORSAllowOrigins []string `mapstructure:"cors_allow_origins"`
	Postgres         PostgresConfig
	JWT              JWTConfig
	SessionRecording SessionRecordingConfig `mapstructure:"session_recording"`
}

type KafkaConfig struct {
	Brokers                          string `mapstructure:"brokers"`
	Topic                            string `mapstructure:"topic"`
	SecurityProtocol                 string `mapstructure:"security_protocol"`
	SessionRecordingEnabled          bool   `mapstructure:"session_recording_enabled"`
	SessionRecordingTopic            string `mapstructure:"session_recording_topic"`
	SessionRecordingBrokers          string `mapstructure:"session_recording_brokers"`
	SessionRecordingSecurityProtocol string `mapstructure:"session_recording_security_protocol"`
	GroupID                          string `mapstructure:"group_id"`
}

func InitConfigs(filename, configPath string) {
	viper.SetConfigName(filename)
	viper.AddConfigPath(configPath)

	viper.SetDefault("kafka.group_id", "livestream")
	viper.SetDefault("kafka.session_recording_enabled", true)
	viper.SetDefault("session_recording.max_lru_entries", 2_000_000_000)

	err := viper.ReadInConfig()
	if err != nil {
		// TODO capture error to PostHog
		log.Fatalf("fatal error config file: %v", err)
	}

	viper.OnConfigChange(func(e fsnotify.Event) {
		log.Printf("Config file changed: %s", e.Name)
	})
	viper.WatchConfig()

	viper.SetEnvPrefix("livestream") // will be uppercased automatically
	replacer := strings.NewReplacer(".", "_")
	viper.SetEnvKeyReplacer(replacer)
	viper.BindEnv("jwt.secret")                        // read from LIVESTREAM_JWT_SECRET
	viper.BindEnv("postgres.url")                      // read from LIVESTREAM_POSTGRES_URL
	viper.BindEnv("session_recording.max_lru_entries") // read from LIVESTREAM_SESSION_RECORDING_MAX_LRU_ENTRIES
}

func LoadConfig() (*Config, error) {
	var config Config

	if err := viper.Unmarshal(&config); err != nil {
		return nil, err
	}

	// Set default values
	if config.Parallelism == 0 {
		config.Parallelism = 1
	}
	if len(config.CORSAllowOrigins) == 0 {
		config.CORSAllowOrigins = []string{"*"}
	}
	if config.Kafka.SecurityProtocol == "" {
		if config.Debug {
			config.Kafka.SecurityProtocol = "PLAINTEXT"
		} else {
			config.Kafka.SecurityProtocol = "SSL"
		}
	}
	if config.Kafka.SessionRecordingEnabled {
		if config.Kafka.SessionRecordingTopic == "" {
			config.Kafka.SessionRecordingTopic = "session_recording_snapshot_item_events"
		}
		if config.Kafka.SessionRecordingBrokers == "" {
			config.Kafka.SessionRecordingBrokers = config.Kafka.Brokers
		}
		if config.Kafka.SessionRecordingSecurityProtocol == "" {
			config.Kafka.SessionRecordingSecurityProtocol = "SSL"
		}
	}

	if config.MMDB.Path == "" {
		return nil, errors.New("mmdb.path must be set")
	}
	if config.Kafka.Brokers == "" {
		return nil, errors.New("kafka.brokers must be set")
	}
	if config.Kafka.Topic == "" {
		return nil, errors.New("kafka.topic must be set")
	}
	if config.Kafka.GroupID == "" {
		return nil, errors.New("kafka.group_id must be set")
	}

	return &config, nil
}
