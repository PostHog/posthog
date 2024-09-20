package main

import (
	"net/http"

	"github.com/labstack/echo/v4"
)

func index(c echo.Context) error {
	return c.String(http.StatusOK, "RealTime Hog 3000")
}
