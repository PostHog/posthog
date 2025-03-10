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
	if err := viper.BindEnv("jwt.secret"); err != nil {
		log.Fatalf("failed to bind jwt.secret env var: %v", err)
	}
	if err := viper.BindEnv("postgres.url"); err != nil {
		log.Fatalf("failed to bind postgres.url env var: %v", err)
	}
}
