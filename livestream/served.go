package main

import (
	"net/http"

	"github.com/labstack/echo/v4"
)

type Counter struct {
	Count uint32
}

func servedHandler(consumer *PostHogKafkaConsumer) func(c echo.Context) error {
	return func(c echo.Context) error {
		count := consumer.counter.Count()
		return c.JSON(http.StatusOK, Counter{Count: uint32(count)})
	}
}
