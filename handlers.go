package main

import (
	"context"
	"net/http"
	"strconv"

	"github.com/labstack/echo/v4"
	"github.com/labstack/gommon/log"
)

func index(c echo.Context) error {
	return c.String(http.StatusOK, "RealTime Hog 3000")
}

func pgVersion(c echo.Context) error {
	conn := getPGConn()
	defer conn.Close(context.Background())

	var version string
	err := conn.QueryRow(context.Background(), "select version()").Scan(&version)
	if err != nil {
		c.Logger().Error("cannot get row: %v", err)
	}

	return c.String(http.StatusOK, version)
}

func getToken(c echo.Context) error {
	teamIdStr := c.QueryParam("teamId")
	teamId, err := strconv.Atoi(teamIdStr)
	if err != nil {
		return err
	}

	token, err := tokenFromTeamId(teamId)
	if err != nil {
		log.Error("query error")
		return err
	}

	return c.String(http.StatusOK, token)
}

func getPerson(c echo.Context) error {
	distinctId := c.QueryParam("distinctId")

	personId, err := personFromDistinctId(distinctId)
	if err != nil {
		log.Error("query error")
		return err
	}

	return c.String(http.StatusOK, strconv.Itoa(personId))
}
