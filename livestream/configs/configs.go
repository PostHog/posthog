package configs

import (
	"errors"
	"log"
	"strings"

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
	SessionTimeoutMs                 int    `mapstructure:"session_timeout_ms"`
	HeartbeatIntervalMs              int    `mapstructure:"heartbeat_interval_ms"`
	MaxPollIntervalMs                int    `mapstructure:"max_poll_interval_ms"`
}

func InitConfigs(filename, configPath string) {
	viper.SetConfigName(filename)
	viper.AddConfigPath(configPath)

	viper.SetDefault("kafka.group_id", "livestream")
	viper.SetDefault("kafka.session_recording_enabled", true)
	viper.SetDefault("session_recording.max_lru_entries", 2_000_000_000)

	if err := viper.ReadInConfig(); err != nil {
		if _, ok := err.(viper.ConfigFileNotFoundError); ok {
			log.Println("No config file found, falling back to environment variables")
		} else {
			log.Fatalf("Error reading config file: %v", err)
		}
	}

	viper.SetEnvPrefix("livestream") // will be uppercased automatically
	replacer := strings.NewReplacer(".", "_")
	viper.SetEnvKeyReplacer(replacer)
	
	// Core settings
	_ = viper.BindEnv("debug")       // LIVESTREAM_DEBUG
	_ = viper.BindEnv("parallelism") // LIVESTREAM_PARALLELISM
	_ = viper.BindEnv("cors_allow_origins") // LIVESTREAM_CORS_ALLOW_ORIGINS

	// GEO settings
	_ = viper.BindEnv("mmdb.path") // LIVESTREAM_MMDB_PATH

	// Kafka settings
	_ = viper.BindEnv("kafka.brokers")                             // LIVESTREAM_KAFKA_BROKERS
	_ = viper.BindEnv("kafka.topic")                               // LIVESTREAM_KAFKA_TOPIC
	_ = viper.BindEnv("kafka.group_id")                            // LIVESTREAM_KAFKA_GROUP_ID
	_ = viper.BindEnv("kafka.security_protocol")                   // LIVESTREAM_KAFKA_SECURITY_PROTOCOL
	_ = viper.BindEnv("kafka.session_recording_enabled")           // LIVESTREAM_KAFKA_SESSION_RECORDING_ENABLED
	_ = viper.BindEnv("kafka.session_recording_topic")             // LIVESTREAM_KAFKA_SESSION_RECORDING_TOPIC
	_ = viper.BindEnv("kafka.session_recording_brokers")           // LIVESTREAM_KAFKA_SESSION_RECORDING_BROKERS
	_ = viper.BindEnv("kafka.session_recording_security_protocol") // LIVESTREAM_KAFKA_SESSION_RECORDING_SECURITY_PROTOCOL
	_ = viper.BindEnv("kafka.session_timeout_ms")                  // LIVESTREAM_KAFKA_SESSION_TIMEOUT_MS
	_ = viper.BindEnv("kafka.heartbeat_interval_ms")               // LIVESTREAM_KAFKA_HEARTBEAT_INTERVAL_MS
	_ = viper.BindEnv("kafka.max_poll_interval_ms")                // LIVESTREAM_KAFKA_MAX_POLL_INTERVAL_MS

	// Postgres settings
	_ = viper.BindEnv("postgres.url") // LIVESTREAM_POSTGRES_URL

	// JWT settings
	_ = viper.BindEnv("jwt.secret") // LIVESTREAM_JWT_SECRET

	// Session recording settings
	_ = viper.BindEnv("session_recording.max_lru_entries") // LIVESTREAM_SESSION_RECORDING_MAX_LRU_ENTRIES
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
