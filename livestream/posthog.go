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

func personFromDistinctId(distinctId string) (int, error) {
	pgConn, pgConnErr := getPGConn()
	if pgConnErr != nil {
		return 0, pgConnErr
	}
	defer pgConn.Close(context.Background())

	var personId int
	queryErr := pgConn.QueryRow(context.Background(), "select person_id from posthog_persondistinctid where distinct_id = $1;", distinctId).Scan(&personId)
	if queryErr != nil {
		return 0, queryErr
	}

	return personId, nil
}
