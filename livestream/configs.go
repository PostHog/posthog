package main

import (
	"fmt"
	"log"
	"strings"

	"github.com/fsnotify/fsnotify"
	"github.com/getsentry/sentry-go"
	"github.com/spf13/viper"
)

func loadConfigs() {
	viper.SetConfigName("configs")
	viper.AddConfigPath("configs/")

	viper.SetDefault("kafka.group_id", "livestream")
	viper.SetDefault("prod", false)

	err := viper.ReadInConfig()
	if err != nil {
		sentry.CaptureException(err)
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
