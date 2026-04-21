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

type RedisConfig struct {
	Address            string `mapstructure:"address"`
	Port               string `mapstructure:"port"`
	TLS                bool   `mapstructure:"tls"`
	FlushIntervalMs    int    `mapstructure:"flush_interval_ms"`
	UsePubSub          bool   `mapstructure:"use_pub_sub"`
	PublishBufferSize  int    `mapstructure:"publish_buffer_size"`
	PublishWorkers     int    `mapstructure:"publish_workers"`
}

// ConsumerConfig holds connection and tuning parameters for a single Kafka consumer.
type ConsumerConfig struct {
	Enabled          bool   `mapstructure:"enabled"`
	Brokers          string `mapstructure:"brokers"`
	Topic            string `mapstructure:"topic"`
	SecurityProtocol string `mapstructure:"security_protocol"`
	GroupID          string `mapstructure:"group_id"`
	ClientID         string `mapstructure:"client_id"`

	// Timeout overrides — zero means use librdkafka defaults.
	SessionTimeoutMs    int `mapstructure:"session_timeout_ms"`
	HeartbeatIntervalMs int `mapstructure:"heartbeat_interval_ms"`
	MaxPollIntervalMs   int `mapstructure:"max_poll_interval_ms"`
}

// ConsumersConfig holds per-consumer Kafka configurations.
type ConsumersConfig struct {
	Event            ConsumerConfig `mapstructure:"event"`
	SessionRecording ConsumerConfig `mapstructure:"session_recording"`
	Notification     ConsumerConfig `mapstructure:"notification"`
}

type Config struct {
	Debug            bool `mapstructure:"debug"`
	MMDB             MMDBConfig
	Consumers        ConsumersConfig `mapstructure:"consumers"`
	Parallelism      int             `mapstructure:"parallelism"`
	CORSAllowOrigins []string        `mapstructure:"cors_allow_origins"`
	Postgres         PostgresConfig
	JWT              JWTConfig
	SessionRecording SessionRecordingConfig `mapstructure:"session_recording"`
	Redis            RedisConfig
}

func InitConfigs(filename, configPath string) {
	viper.SetConfigName(filename)
	viper.AddConfigPath(configPath)

	viper.SetDefault("consumers.event.enabled", true)
	viper.SetDefault("consumers.session_recording.enabled", true)
	viper.SetDefault("consumers.notification.enabled", false)
	viper.SetDefault("session_recording.max_lru_entries", 2_000_000_000)
	viper.SetDefault("redis.flush_interval_ms", 500)

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
	_ = viper.BindEnv("debug")              // LIVESTREAM_DEBUG
	_ = viper.BindEnv("parallelism")        // LIVESTREAM_PARALLELISM
	_ = viper.BindEnv("cors_allow_origins") // LIVESTREAM_CORS_ALLOW_ORIGINS

	// GEO settings
	_ = viper.BindEnv("mmdb.path") // LIVESTREAM_MMDB_PATH

	// Per-consumer settings
	_ = viper.BindEnv("consumers.event.enabled")               // LIVESTREAM_CONSUMERS_EVENT_ENABLED
	_ = viper.BindEnv("consumers.event.brokers")               // LIVESTREAM_CONSUMERS_EVENT_BROKERS
	_ = viper.BindEnv("consumers.event.topic")                 // LIVESTREAM_CONSUMERS_EVENT_TOPIC
	_ = viper.BindEnv("consumers.event.security_protocol")     // LIVESTREAM_CONSUMERS_EVENT_SECURITY_PROTOCOL
	_ = viper.BindEnv("consumers.event.group_id")              // LIVESTREAM_CONSUMERS_EVENT_GROUP_ID
	_ = viper.BindEnv("consumers.event.client_id")             // LIVESTREAM_CONSUMERS_EVENT_CLIENT_ID
	_ = viper.BindEnv("consumers.event.session_timeout_ms")    // LIVESTREAM_CONSUMERS_EVENT_SESSION_TIMEOUT_MS
	_ = viper.BindEnv("consumers.event.heartbeat_interval_ms") // LIVESTREAM_CONSUMERS_EVENT_HEARTBEAT_INTERVAL_MS
	_ = viper.BindEnv("consumers.event.max_poll_interval_ms")  // LIVESTREAM_CONSUMERS_EVENT_MAX_POLL_INTERVAL_MS

	_ = viper.BindEnv("consumers.session_recording.enabled")               // LIVESTREAM_CONSUMERS_SESSION_RECORDING_ENABLED
	_ = viper.BindEnv("consumers.session_recording.brokers")               // LIVESTREAM_CONSUMERS_SESSION_RECORDING_BROKERS
	_ = viper.BindEnv("consumers.session_recording.topic")                 // LIVESTREAM_CONSUMERS_SESSION_RECORDING_TOPIC
	_ = viper.BindEnv("consumers.session_recording.security_protocol")     // LIVESTREAM_CONSUMERS_SESSION_RECORDING_SECURITY_PROTOCOL
	_ = viper.BindEnv("consumers.session_recording.group_id")              // LIVESTREAM_CONSUMERS_SESSION_RECORDING_GROUP_ID
	_ = viper.BindEnv("consumers.session_recording.client_id")             // LIVESTREAM_CONSUMERS_SESSION_RECORDING_CLIENT_ID
	_ = viper.BindEnv("consumers.session_recording.session_timeout_ms")    // LIVESTREAM_CONSUMERS_SESSION_RECORDING_SESSION_TIMEOUT_MS
	_ = viper.BindEnv("consumers.session_recording.heartbeat_interval_ms") // LIVESTREAM_CONSUMERS_SESSION_RECORDING_HEARTBEAT_INTERVAL_MS
	_ = viper.BindEnv("consumers.session_recording.max_poll_interval_ms")  // LIVESTREAM_CONSUMERS_SESSION_RECORDING_MAX_POLL_INTERVAL_MS

	_ = viper.BindEnv("consumers.notification.enabled")               // LIVESTREAM_CONSUMERS_NOTIFICATION_ENABLED
	_ = viper.BindEnv("consumers.notification.brokers")               // LIVESTREAM_CONSUMERS_NOTIFICATION_BROKERS
	_ = viper.BindEnv("consumers.notification.topic")                 // LIVESTREAM_CONSUMERS_NOTIFICATION_TOPIC
	_ = viper.BindEnv("consumers.notification.security_protocol")     // LIVESTREAM_CONSUMERS_NOTIFICATION_SECURITY_PROTOCOL
	_ = viper.BindEnv("consumers.notification.group_id")              // LIVESTREAM_CONSUMERS_NOTIFICATION_GROUP_ID
	_ = viper.BindEnv("consumers.notification.client_id")             // LIVESTREAM_CONSUMERS_NOTIFICATION_CLIENT_ID
	_ = viper.BindEnv("consumers.notification.session_timeout_ms")    // LIVESTREAM_CONSUMERS_NOTIFICATION_SESSION_TIMEOUT_MS
	_ = viper.BindEnv("consumers.notification.heartbeat_interval_ms") // LIVESTREAM_CONSUMERS_NOTIFICATION_HEARTBEAT_INTERVAL_MS
	_ = viper.BindEnv("consumers.notification.max_poll_interval_ms")  // LIVESTREAM_CONSUMERS_NOTIFICATION_MAX_POLL_INTERVAL_MS

	// Postgres settings
	_ = viper.BindEnv("postgres.url") // LIVESTREAM_POSTGRES_URL

	// JWT settings
	_ = viper.BindEnv("jwt.secret") // LIVESTREAM_JWT_SECRET

	// Session recording settings
	_ = viper.BindEnv("session_recording.max_lru_entries") // LIVESTREAM_SESSION_RECORDING_MAX_LRU_ENTRIES

	// Redis settings
	_ = viper.BindEnv("redis.address")             // LIVESTREAM_REDIS_ADDRESS
	_ = viper.BindEnv("redis.port")                // LIVESTREAM_REDIS_PORT
	_ = viper.BindEnv("redis.tls")                 // LIVESTREAM_REDIS_TLS
	_ = viper.BindEnv("redis.flush_interval_ms")   // LIVESTREAM_REDIS_FLUSH_INTERVAL_MS
	_ = viper.BindEnv("redis.use_pub_sub")         // LIVESTREAM_REDIS_USE_PUB_SUB
	_ = viper.BindEnv("redis.publish_buffer_size") // LIVESTREAM_REDIS_PUBLISH_BUFFER_SIZE
	_ = viper.BindEnv("redis.publish_workers")     // LIVESTREAM_REDIS_PUBLISH_WORKERS
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

	if config.MMDB.Path == "" {
		return nil, errors.New("mmdb.path must be set")
	}

	// Validate enabled consumer configs
	if err := validateConsumerConfig("event", config.Consumers.Event); err != nil {
		return nil, err
	}
	if err := validateConsumerConfig("session_recording", config.Consumers.SessionRecording); err != nil {
		return nil, err
	}
	if err := validateConsumerConfig("notification", config.Consumers.Notification); err != nil {
		return nil, err
	}

	if config.Redis.PublishBufferSize == 0 {
		config.Redis.PublishBufferSize = 10000
	}
	if config.Redis.PublishWorkers == 0 {
		config.Redis.PublishWorkers = 256
	}

	if config.Redis.FlushIntervalMs < 50 {
		log.Printf("redis.flush_interval_ms=%d is below minimum 50, using default 500", config.Redis.FlushIntervalMs)
		config.Redis.FlushIntervalMs = 500
	}

	return &config, nil
}

func validateConsumerConfig(name string, c ConsumerConfig) error {
	if !c.Enabled {
		return nil
	}
	if c.Brokers == "" {
		return errors.New("consumers." + name + ".brokers must be set")
	}
	if c.Topic == "" {
		return errors.New("consumers." + name + ".topic must be set")
	}
	if c.SecurityProtocol == "" {
		return errors.New("consumers." + name + ".security_protocol must be set")
	}
	if c.GroupID == "" {
		return errors.New("consumers." + name + ".group_id must be set")
	}
	return nil
}
