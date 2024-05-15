package main

import (
	"context"
)

func tokenFromTeamId(teamId int) (string, error) {
	pgConn := getPGConn()
	defer pgConn.Close(context.Background())

	var token string
	err := pgConn.QueryRow(context.Background(), "select api_token from posthog_team where id = $1;", teamId).Scan(&token)

	if err != nil {
		return "", err
	}

	return token, nil
}

func personFromDistinctId(distinctId string) (int, error) {
	pgConn := getPGConn()
	defer pgConn.Close(context.Background())

	var personId int
	err := pgConn.QueryRow(context.Background(), "select person_id from posthog_persondistinctid where distinct_id = $1;", distinctId).Scan(&personId)

	if err != nil {
		return 0, err
	}

	return personId, nil
}
