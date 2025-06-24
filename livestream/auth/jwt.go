package auth

import (
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/golang-jwt/jwt/v5"
	"github.com/labstack/echo/v4"
	"github.com/spf13/viper"
)

const ExpectedScope = "posthog:livestream"

func GetAuth(header http.Header) (jwt.MapClaims, error) {
	authHeader := header.Get("Authorization")
	if authHeader == "" {
		return nil, echo.NewHTTPError(http.StatusUnauthorized, "authorization header is required")
	}

	claims, err := decodeAuthToken(authHeader)
	if err != nil {
		return nil, echo.NewHTTPError(http.StatusUnauthorized, err)
	}
	return claims, nil
}

func getDataFromClaims(claims jwt.MapClaims) (teamID int, token string, err error) {
	team, ok := claims["team_id"].(float64)
	if !ok {
		return 0, "", errors.New("invalid team_id")
	}
	token, ok = claims["api_token"].(string)
	if !ok {
		return 0, "", errors.New("invalid api_token")
	}
	teamID = int(team)
	return teamID, token, nil
}

func GetAuthClaims(header http.Header) (teamID int, token string, err error) {
	claims, err := GetAuth(header)
	if err != nil {
		return 0, "", err
	}

	return getDataFromClaims(claims)

}

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
		return []byte(viper.GetString("jwt.secret")), nil
	})

	if err != nil {
		return nil, err
	}

	// Check if the token is valid and return the claims.
	if claims, ok := token.Claims.(jwt.MapClaims); ok && token.Valid {
		// Validate audience
		tokenScope := fmt.Sprint(claims["aud"])
		if tokenScope != ExpectedScope {
			return nil, errors.New("invalid audience")
		}
		return claims, nil
	} else {
		return nil, errors.New("invalid token")
	}
}
