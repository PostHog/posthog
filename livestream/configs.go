package main

import (
	"fmt"
	"log"

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
		log.Fatalf("fatal error config file: %w", err)
	}

	viper.OnConfigChange(func(e fsnotify.Event) {
		fmt.Println("Config file changed:", e.Name)
	})
	viper.WatchConfig()
}
