package main

import (
	"context"
	"log"

	"github.com/jackc/pgx/v5"
	"github.com/spf13/viper"
)

func getPGConn() *pgx.Conn {
	url := viper.GetString("postgres.url")
	conn, err := pgx.Connect(context.Background(), url)
	if err != nil {
		log.Panicf("Unable to connect to database: %v\n", err)
	}
	return conn
}
