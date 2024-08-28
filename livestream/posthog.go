package main

import (
	"context"
)

func tokenFromTeamId(teamId int) (string, error) {
	pgConn, pgConnErr := getPGConn()
	if pgConnErr != nil {
		return "", pgConnErr
	}
	defer pgConn.Close(context.Background())

	var token string
	queryErr := pgConn.QueryRow(context.Background(), "select api_token from posthog_team where id = $1;", teamId).Scan(&token)
	if queryErr != nil {
		return "", queryErr
	}

	return token, nil
}
