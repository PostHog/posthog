package main

import (
	"context"

	"github.com/jackc/pgx/v5"
	"github.com/spf13/viper"
)

func getPGConn() (*pgx.Conn, error) {
	url := viper.GetString("postgres.url")
	conn, err := pgx.Connect(context.Background(), url)
	if err != nil {
		// TODO capture error to PostHog
		return nil, err
	}
	return conn, nil
}
