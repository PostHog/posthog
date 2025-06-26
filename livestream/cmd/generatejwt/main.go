package main

import (
	"flag"
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/posthog/posthog/livestream/auth"
)

func main() {
	teamIDStr := flag.String("teamid", "", "Team ID (integer)")
	apiToken := flag.String("token", "", "API Token (string)")
	flag.Parse()

	if *teamIDStr == "" || *apiToken == "" {
		fmt.Println("Usage: go run main.go -teamid <team_id> -token <api_token>") // Updated usage message
		fmt.Println("Please provide both -teamid and -token flags.")
		os.Exit(1)
	}

	teamID, err := strconv.ParseInt(*teamIDStr, 10, 64)
	if err != nil {
		fmt.Printf("Error parsing team_id: %v. It must be an integer.\n", err)
		os.Exit(1)
	}

	jwtSecret := os.Getenv("LIVESTREAM_JWT_SECRET")
	if jwtSecret == "" {
		fmt.Println("Error: LIVESTREAM_JWT_SECRET environment variable not set.")
		fmt.Println("Please set this to the same JWT secret used by your application.")
		os.Exit(1)
	}
	mySigningKey := []byte(jwtSecret)

	claims := jwt.MapClaims{
		"team_id":   float64(teamID), // As expected by your existing getDataFromClaims
		"api_token": *apiToken,
		"aud":       auth.ExpectedScope,
		"exp":       time.Now().Add(time.Hour * 72).Unix(), // Token expires in 3 days
		"iat":       time.Now().Unix(),                     // Issued at
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signedToken, err := token.SignedString(mySigningKey)
	if err != nil {
		fmt.Printf("Error creating signed token: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Generated JWT (use this as the Bearer token):\nBearer %s\n", signedToken)
}
