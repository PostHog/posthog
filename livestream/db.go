package main

import (
	"context"

	"github.com/getsentry/sentry-go"
	"github.com/jackc/pgx/v5"
	"github.com/spf13/viper"
)

func getPGConn() (*pgx.Conn, error) {
	url := viper.GetString("postgres.url")
	conn, err := pgx.Connect(context.Background(), url)
	if err != nil {
		sentry.CaptureException(err)
		return nil, err
	}
	return conn, nil
}
