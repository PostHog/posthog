package configs

import (
	"errors"
	"fmt"
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

type Config struct {
	Debug            bool `mapstructure:"debug"`
	MMDB             MMDBConfig
	Kafka            KafkaConfig
	Parallelism      int      `mapstructure:"parallelism"`
	CORSAllowOrigins []string `mapstructure:"cors_allow_origins"`
	Postgres         PostgresConfig
	JWT              JWTConfig
}

type KafkaConfig struct {
	Brokers string `mapstructure:"brokers"`
	Topic   string `mapstructure:"topic"`
	GroupID string `mapstructure:"group_id"`
}

func InitConfigs(filename, configPath string) {
	viper.SetConfigName(filename)
	viper.AddConfigPath(configPath)

	viper.SetDefault("kafka.group_id", "livestream")

	err := viper.ReadInConfig()
	if err != nil {
		// TODO capture error to PostHog
		log.Fatalf("fatal error config file: %v", err)
	}

	viper.OnConfigChange(func(e fsnotify.Event) {
		fmt.Println("Config file changed:", e.Name)
	})
	viper.WatchConfig()

	viper.SetEnvPrefix("livestream") // will be uppercased automatically
	replacer := strings.NewReplacer(".", "_")
	viper.SetEnvKeyReplacer(replacer)
	viper.BindEnv("jwt.secret")   // read from LIVESTREAM_JWT_SECRET
	viper.BindEnv("postgres.url") // read from LIVESTREAM_POSTGRES_URL
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
