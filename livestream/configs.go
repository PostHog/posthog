package main

import (
	"fmt"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"
	"tailscale.com/ipn"
)

func loadConfigs() {
	viper.SetConfigName("configs")
	viper.AddConfigPath("configs/")

	viper.SetDefault("tailscale.controlUrl", ipn.DefaultControlURL)
	viper.SetDefault("kafka.group_id", "livestream")
	viper.SetDefault("prod", false)

	err := viper.ReadInConfig()
	if err != nil {
		panic(fmt.Errorf("fatal error config file: %w", err))
	}

	viper.OnConfigChange(func(e fsnotify.Event) {
		fmt.Println("Config file changed:", e.Name)
	})
	viper.WatchConfig()
}
