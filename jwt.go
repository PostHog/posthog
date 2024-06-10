package main

import (
	"errors"
	"fmt"
	"strings"

	"github.com/golang-jwt/jwt"
	"github.com/spf13/viper"
)

const ExpectedScope = "posthog:livestream"

func decodeAuthToken(authHeader string) (jwt.MapClaims, error) {
	// split the token
	parts := strings.Split(authHeader, " ")
	if len(parts) != 2 {
		return nil, errors.New("invalid token")
	}

	// Check if the Authorization header is in the correct format.
	bearerToken := strings.Split(authHeader, " ")
	if len(bearerToken) != 2 || bearerToken[0] != "Bearer" {
		return nil, fmt.Errorf("authorization header format must be 'Bearer {token}'")
	}

	// Parse the token.
	token, err := jwt.Parse(bearerToken[1], func(token *jwt.Token) (interface{}, error) {
		// Make sure the token's signature algorithm isn't 'none'
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		// Here you should specify the secret used to sign your JWTs.
		return []byte(viper.GetString("jwt.token")), nil
	})

	if err != nil {
		return nil, err
	}

	// Check if the token is valid and return the claims.
	if claims, ok := token.Claims.(jwt.MapClaims); ok && token.Valid {
		// Validate scope
		tokenScope := fmt.Sprint(claims["scope"])
		if tokenScope != ExpectedScope {
			return nil, fmt.Errorf("invalid scope")
		}
		return claims, nil
	} else {
		return nil, fmt.Errorf("invalid token")
	}
}
