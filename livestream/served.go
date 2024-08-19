package main

import (
	"errors"
	"fmt"
	"net/http"

	"github.com/hashicorp/golang-lru/v2/expirable"
	"github.com/labstack/echo/v4"
)

type Counter struct {
	EventCount int
	UserCount  int
}

func servedHandler(stats *Stats) func(c echo.Context) error {
	return func(c echo.Context) error {
		userCount := stats.GlobalStore.Len()
		count := stats.Counter.Count()
		resp := Counter{
			EventCount: count,
			UserCount:  userCount,
		}
		return c.JSON(http.StatusOK, resp)
	}
}

func statsHandler(stats *Stats) func(c echo.Context) error {
	return func(c echo.Context) error {

		type resp struct {
			UsersOnProduct int    `json:"users_on_product,omitempty"`
			Error          string `json:"error,omitempty"`
		}

		authHeader := c.Request().Header.Get("Authorization")
		if authHeader == "" {
			return errors.New("authorization header is required")
		}

		claims, err := decodeAuthToken(authHeader)
		if err != nil {
			return err
		}
		token := fmt.Sprint(claims["api_token"])

		var hash *expirable.LRU[string, string]
		var ok bool
		if hash, ok = stats.Store[token]; !ok {
			resp := resp{
				Error: "no stats",
			}
			return c.JSON(http.StatusNotFound, resp)
		}

		siteStats := resp{
			UsersOnProduct: hash.Len(),
		}
		return c.JSON(http.StatusOK, siteStats)
	}
}
