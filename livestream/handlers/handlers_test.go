package handlers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"testing/synctest"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/golang-jwt/jwt/v5"
	"github.com/labstack/echo/v4"
	"github.com/posthog/posthog/livestream/auth"
	"github.com/posthog/posthog/livestream/events"
	"github.com/redis/rueidis"
	"github.com/spf13/viper"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return f(request)
}

type flushRecorder struct {
	*httptest.ResponseRecorder
	flushed chan string
}

func (r *flushRecorder) Flush() {
	r.ResponseRecorder.Flush()
	select {
	case r.flushed <- r.Body.String():
	default:
	}
}

type notificationRedisClient struct {
	rueidis.Client
	receiveCallback chan func(rueidis.PubSubMessage)
	receiveCanceled chan struct{}
}

func (c *notificationRedisClient) Receive(
	ctx context.Context,
	_ rueidis.Completed,
	callback func(rueidis.PubSubMessage),
) error {
	c.receiveCallback <- callback
	<-ctx.Done()
	close(c.receiveCanceled)
	return ctx.Err()
}

func TestStreamEventsHandler_AuthValidation(t *testing.T) {
	logger := echo.New().Logger
	subChan := make(chan events.Subscription, 10)
	unSubChan := make(chan events.Subscription, 10)
	handler := StreamEventsHandler(logger, subChan, unSubChan)

	tests := []struct {
		name           string
		description    string
		setupHeader    func(*http.Request)
		expectedStatus int
		expectedError  string
	}{
		{
			name:        "Missing authorization header returns unauthorized",
			description: "When auth header is missing, handler should return 401 with 'wrong token'",
			setupHeader: func(req *http.Request) {
			},
			expectedStatus: http.StatusUnauthorized,
			expectedError:  "wrong token",
		},
		{
			name:        "Invalid auth header returns unauthorized",
			description: "When auth header is invalid (not Bearer format), handler should return 401 with 'wrong token'",
			setupHeader: func(req *http.Request) {
				req.Header.Set("Authorization", "InvalidToken")
			},
			expectedStatus: http.StatusUnauthorized,
			expectedError:  "wrong token",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			e := echo.New()
			req := httptest.NewRequest(http.MethodGet, "/events", nil)
			ctx, canc := context.WithTimeout(context.Background(), time.Millisecond)
			defer canc()
			req = req.WithContext(ctx)
			tt.setupHeader(req)
			rec := httptest.NewRecorder()
			c := e.NewContext(req, rec)

			err := handler(c)

			require.Error(t, err, tt.description)
			httpErr, ok := err.(*echo.HTTPError)
			require.True(t, ok, "error should be an HTTPError")
			assert.Equal(t, tt.expectedStatus, httpErr.Code)
			assert.Equal(t, tt.expectedError, httpErr.Message)
		})
	}
}

func TestStreamEventsHandler_TokenAndTeamIDValidation(t *testing.T) {
	viper.Set("jwt.secret", "test-secret-for-handlers")

	logger := echo.New().Logger
	subChan := make(chan events.Subscription, 10)
	unSubChan := make(chan events.Subscription, 10)
	handler := StreamEventsHandler(logger, subChan, unSubChan)

	tests := []struct {
		name         string
		description  string
		claims       jwt.MapClaims
		expectError  bool
		errorMessage string
	}{
		{
			name:        "Empty api_token should return unauthorized",
			description: "New validation: empty token in JWT claims should be rejected with 401",
			claims: jwt.MapClaims{
				"team_id":   123,
				"api_token": "",
			},
			expectError:  true,
			errorMessage: "wrong token",
		},
		{
			name:        "Team ID 0 should return unauthorized",
			description: "New validation: teamID=0 in JWT claims should be rejected with 401",
			claims: jwt.MapClaims{
				"team_id":   0,
				"api_token": "valid-token",
			},
			expectError:  true,
			errorMessage: "wrong token",
		},
		{
			name:        "Valid token and team ID succeeds",
			description: "New validation: teamID=7 and non-empty token should pass validation",
			claims: jwt.MapClaims{
				"team_id":   7,
				"api_token": "valid-token",
			},
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			token := createJWTToken(auth.ExpectedScope, tt.claims)

			e := echo.New()
			req := httptest.NewRequest(http.MethodGet, "/events", nil)
			req.Header.Set("Authorization", "Bearer "+token)
			ctx, canc := context.WithTimeout(context.Background(), time.Millisecond)
			defer canc()
			req = req.WithContext(ctx)
			rec := httptest.NewRecorder()
			c := e.NewContext(req, rec)

			err := handler(c)

			if tt.expectError {
				require.Error(t, err, tt.description)
				httpErr, ok := err.(*echo.HTTPError)
				require.True(t, ok, "error should be an HTTPError")
				assert.Equal(t, http.StatusUnauthorized, httpErr.Code)
				assert.Equal(t, tt.errorMessage, httpErr.Message)
			} else {
				assert.NoError(t, err, tt.description)
			}
		})
	}
}

func createJWTToken(audience string, claims jwt.MapClaims) string {
	newClaims := jwt.MapClaims{
		"aud": audience,
		"exp": time.Now().Add(time.Hour).Unix(),
	}
	for k, v := range claims {
		newClaims[k] = v
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, newClaims)
	tokenString, _ := token.SignedString([]byte(viper.GetString("jwt.secret")))
	return tokenString
}

func TestStreamEventsHandlerDeliversEventsDuringPeriodicAccessCheck(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		viper.Set("jwt.secret", "test-periodic-access-secret")
		viper.Set("jwt.authorization_url", "http://authorization.test")
		defer viper.Set("jwt.authorization_url", "")

		var calls atomic.Int32
		var activeCalls atomic.Int32
		var maxActiveCalls atomic.Int32
		periodicStarted := make(chan struct{})
		periodicStatus := make(chan int)
		originalTransport := http.DefaultTransport
		http.DefaultTransport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
			call := calls.Add(1)
			active := activeCalls.Add(1)
			for {
				maxActive := maxActiveCalls.Load()
				if active <= maxActive || maxActiveCalls.CompareAndSwap(maxActive, active) {
					break
				}
			}
			defer activeCalls.Add(-1)

			if call == 1 {
				return accessResponse(http.StatusNoContent), nil
			}
			if call == 2 {
				close(periodicStarted)
			}
			select {
			case status := <-periodicStatus:
				return accessResponse(status), nil
			case <-request.Context().Done():
				return nil, request.Context().Err()
			}
		})
		defer func() { http.DefaultTransport = originalTransport }()

		requestContext, cancelRequest := context.WithCancel(context.Background())
		defer cancelRequest()
		request := httptest.NewRequest(http.MethodGet, "/events", nil).WithContext(requestContext)
		request.Header.Set("Authorization", "Bearer "+createJWTToken(auth.ExpectedScope, jwt.MapClaims{
			"team_id": 1, "api_token": "test-project-token",
		}))
		recorder := &flushRecorder{ResponseRecorder: httptest.NewRecorder(), flushed: make(chan string, 1)}
		e := echo.New()
		subChan := make(chan events.Subscription, 1)
		unSubChan := make(chan events.Subscription, 1)
		done := make(chan error, 1)
		go func() {
			done <- StreamEventsHandler(e.Logger, subChan, unSubChan)(e.NewContext(request, recorder))
		}()

		subscription := <-subChan
		time.Sleep(30 * time.Second)
		<-periodicStarted

		subscription.EventChan <- map[string]string{"event": "received"}
		<-recorder.flushed
		assert.Contains(t, recorder.Body.String(), `"event":"received"`)
		assert.Equal(t, int32(2), calls.Load())
		assert.Equal(t, int32(1), maxActiveCalls.Load())

		periodicStatus <- http.StatusForbidden
		require.NoError(t, <-done)
	})
}

func TestNotificationsHandlerDeliversMessagesDuringPeriodicAccessCheck(t *testing.T) {
	miniredisServer := miniredis.RunT(t)
	client, err := rueidis.NewClient(rueidis.ClientOption{
		InitAddress:  []string{miniredisServer.Addr()},
		DisableCache: true,
	})
	require.NoError(t, err)
	defer client.Close()

	synctest.Test(t, func(t *testing.T) {
		viper.Set("jwt.secret", "test-notification-access-secret")
		viper.Set("jwt.authorization_url", "http://authorization.test")
		defer viper.Set("jwt.authorization_url", "")

		var calls atomic.Int32
		periodicStarted := make(chan struct{})
		periodicStatus := make(chan int)
		originalTransport := http.DefaultTransport
		http.DefaultTransport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
			if calls.Add(1) == 1 {
				return accessResponse(http.StatusNoContent), nil
			}
			close(periodicStarted)
			select {
			case status := <-periodicStatus:
				return accessResponse(status), nil
			case <-request.Context().Done():
				return nil, request.Context().Err()
			}
		})
		defer func() { http.DefaultTransport = originalTransport }()

		redisClient := &notificationRedisClient{
			Client:          client,
			receiveCallback: make(chan func(rueidis.PubSubMessage), 1),
			receiveCanceled: make(chan struct{}),
		}

		requestContext, cancelRequest := context.WithCancel(context.Background())
		defer cancelRequest()
		request := httptest.NewRequest(http.MethodGet, "/notifications", nil).WithContext(requestContext)
		request.Header.Set("Authorization", "Bearer "+createJWTToken(auth.ExpectedScope, jwt.MapClaims{
			"team_id": 1, "api_token": "test-project-token", "user_id": 42, "organization_id": "test-organization",
		}))
		recorder := &flushRecorder{ResponseRecorder: httptest.NewRecorder(), flushed: make(chan string, 2)}
		e := echo.New()
		done := make(chan error, 1)
		go func() {
			done <- NotificationsHandler(redisClient)(e.NewContext(request, recorder))
		}()

		receive := <-redisClient.receiveCallback
		time.Sleep(15 * time.Second)
		<-periodicStarted
		receive(rueidis.PubSubMessage{Message: `{"resolved_user_ids":[42],"body":"delivered"}`})

		for {
			body := <-recorder.flushed
			if strings.Contains(body, `"body":"delivered"`) {
				break
			}
		}

		periodicStatus <- http.StatusForbidden
		require.NoError(t, <-done)
		<-redisClient.receiveCanceled
	})
}

func TestStreamEventsHandlerCancelsPeriodicAccessCheck(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		viper.Set("jwt.secret", "test-periodic-cancel-secret")
		viper.Set("jwt.authorization_url", "http://authorization.test")
		defer viper.Set("jwt.authorization_url", "")

		var calls atomic.Int32
		periodicStarted := make(chan struct{})
		periodicCanceled := make(chan struct{})
		originalTransport := http.DefaultTransport
		http.DefaultTransport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
			if calls.Add(1) == 1 {
				return accessResponse(http.StatusNoContent), nil
			}
			close(periodicStarted)
			<-request.Context().Done()
			close(periodicCanceled)
			return nil, request.Context().Err()
		})
		defer func() { http.DefaultTransport = originalTransport }()

		requestContext, cancelRequest := context.WithCancel(context.Background())
		request := httptest.NewRequest(http.MethodGet, "/events", nil).WithContext(requestContext)
		request.Header.Set("Authorization", "Bearer "+createJWTToken(auth.ExpectedScope, jwt.MapClaims{
			"team_id": 1, "api_token": "test-project-token",
		}))
		e := echo.New()
		subChan := make(chan events.Subscription, 1)
		unSubChan := make(chan events.Subscription, 1)
		done := make(chan error, 1)
		go func() {
			done <- StreamEventsHandler(e.Logger, subChan, unSubChan)(e.NewContext(request, httptest.NewRecorder()))
		}()

		<-subChan
		time.Sleep(30 * time.Second)
		<-periodicStarted
		cancelRequest()

		require.NoError(t, <-done)
		<-periodicCanceled
	})
}

func accessResponse(status int) *http.Response {
	return &http.Response{
		StatusCode: status,
		Body:       http.NoBody,
		Header:     make(http.Header),
	}
}

func TestHandlersRejectRevokedAccess(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	}))
	defer server.Close()
	viper.Set("jwt.authorization_url", server.URL)
	t.Cleanup(func() { viper.Set("jwt.authorization_url", "") })
	viper.Set("jwt.secret", "test-revoked-access-secret")
	token := createJWTToken(auth.ExpectedScope, jwt.MapClaims{
		"team_id": 1, "api_token": "test-project-token", "user_id": 1, "organization_id": "test-organization",
	})
	e := echo.New()
	for name, handler := range map[string]echo.HandlerFunc{
		"stats":         StatsHandler(nil, nil, nil),
		"events":        StreamEventsHandler(e.Logger, make(chan events.Subscription, 1), make(chan events.Subscription, 1)),
		"notifications": NotificationsHandler(nil),
	} {
		t.Run(name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			request := httptest.NewRequest(http.MethodGet, "/", nil).WithContext(ctx)
			request.Header.Set("Authorization", "Bearer "+token)
			var httpError *echo.HTTPError
			require.ErrorAs(t, handler(e.NewContext(request, httptest.NewRecorder())), &httpError)
			assert.Equal(t, http.StatusUnauthorized, httpError.Code)
		})
	}
}

func TestStatsHandler_ReadsFromRedis(t *testing.T) {
	viper.Set("jwt.secret", "test-secret-for-stats")
	apiToken := "phx_test_token"

	mr := miniredis.RunT(t)
	client, err := rueidis.NewClient(rueidis.ClientOption{
		InitAddress:  []string{mr.Addr()},
		DisableCache: true,
	})
	require.NoError(t, err)
	t.Cleanup(func() { client.Close() })
	rw := events.NewStatsInRedisFromClient(client)

	ctx := context.Background()
	require.NoError(t, rw.AddUser(ctx, apiToken, "user1"))
	require.NoError(t, rw.AddUser(ctx, apiToken, "user2"))
	require.NoError(t, rw.AddSession(ctx, apiToken, "sess1"))

	stats := events.NewStatsKeeper()
	sessionStats := events.NewSessionStatsKeeper(0, 0)

	handler := StatsHandler(stats, sessionStats, rw)

	token := createJWTToken(auth.ExpectedScope, jwt.MapClaims{
		"team_id":   1,
		"api_token": apiToken,
	})

	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/stats", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	err = handler(c)
	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, rec.Code)

	var resp struct {
		UsersOnProduct   int    `json:"users_on_product"`
		ActiveRecordings int    `json:"active_recordings"`
		Error            string `json:"error"`
	}
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
	assert.Equal(t, 2, resp.UsersOnProduct)
	assert.Equal(t, 1, resp.ActiveRecordings)
	assert.Empty(t, resp.Error)
}

func TestStatsHandler_FallsBackToLocal(t *testing.T) {
	viper.Set("jwt.secret", "test-secret-for-stats")
	apiToken := "phx_test_token"

	stats := events.NewStatsKeeper()
	stats.GetStoreForToken(apiToken).Add("user1", events.NoSpaceType{})
	stats.GetStoreForToken(apiToken).Add("user2", events.NoSpaceType{})
	stats.GetStoreForToken(apiToken).Add("user3", events.NoSpaceType{})

	sessionStats := events.NewSessionStatsKeeper(0, 0)
	sessionStats.Add(apiToken, "sess1")
	sessionStats.Add(apiToken, "sess2")

	handler := StatsHandler(stats, sessionStats, nil)

	token := createJWTToken(auth.ExpectedScope, jwt.MapClaims{
		"team_id":   1,
		"api_token": apiToken,
	})

	e := echo.New()
	req := httptest.NewRequest(http.MethodGet, "/stats", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	c := e.NewContext(req, rec)

	err := handler(c)
	require.NoError(t, err)
	assert.Equal(t, http.StatusOK, rec.Code)

	var resp struct {
		UsersOnProduct   int    `json:"users_on_product"`
		ActiveRecordings int    `json:"active_recordings"`
		Error            string `json:"error"`
	}
	require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &resp))
	assert.Equal(t, 3, resp.UsersOnProduct)
	assert.Equal(t, 2, resp.ActiveRecordings)
	assert.Empty(t, resp.Error)
}

func TestFilterNotificationForUser(t *testing.T) {
	const userID = 42

	tests := []struct {
		name       string
		payload    string
		wantOK     bool
		wantReason string
		wantHasKey string // a key expected to be present in cleaned output when delivered
	}{
		{
			name:       "invalid json -> malformed_payload",
			payload:    "not-json",
			wantOK:     false,
			wantReason: "malformed_payload",
		},
		{
			name:       "missing resolved_user_ids -> malformed_payload",
			payload:    `{"id": "n1"}`,
			wantOK:     false,
			wantReason: "malformed_payload",
		},
		{
			name:       "resolved_user_ids wrong type -> malformed_payload",
			payload:    `{"id": "n1", "resolved_user_ids": "42"}`,
			wantOK:     false,
			wantReason: "malformed_payload",
		},
		{
			name:       "user not in list -> wrong_user",
			payload:    `{"id": "n1", "resolved_user_ids": [1, 2, 3]}`,
			wantOK:     false,
			wantReason: "wrong_user",
		},
		{
			name:       "user in list -> delivered, resolved_user_ids stripped",
			payload:    `{"id": "n1", "resolved_user_ids": [1, 42, 3], "body": "hi"}`,
			wantOK:     true,
			wantHasKey: "body",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cleaned, ok, reason := filterNotificationForUser(tt.payload, userID)
			assert.Equal(t, tt.wantOK, ok)
			assert.Equal(t, tt.wantReason, reason)
			if ok {
				var out map[string]interface{}
				require.NoError(t, json.Unmarshal([]byte(cleaned), &out))
				_, present := out["resolved_user_ids"]
				assert.False(t, present, "resolved_user_ids must be stripped from delivered payload")
				if tt.wantHasKey != "" {
					_, present := out[tt.wantHasKey]
					assert.True(t, present, "expected key %q in cleaned payload", tt.wantHasKey)
				}
			} else {
				assert.Empty(t, cleaned)
			}
		})
	}
}

type filterShape struct {
	Key      string
	Operator string
	Values   []string
}

func shapesOf(filters []events.CompiledPropertyFilter) []filterShape {
	if filters == nil {
		return nil
	}
	out := make([]filterShape, 0, len(filters))
	for _, f := range filters {
		out = append(out, filterShape{Key: f.Key, Operator: f.Operator, Values: f.Values})
	}
	return out
}

func TestParsePropertyFilters(t *testing.T) {
	tests := []struct {
		name           string
		propertiesJSON string
		legacy         []string
		want           []filterShape
	}{
		{
			name: "no input returns nil",
			want: nil,
		},
		{
			name:   "legacy single key=value as exact",
			legacy: []string{"$browser=Chrome"},
			want:   []filterShape{{Key: "$browser", Operator: events.OpExact, Values: []string{"Chrome"}}},
		},
		{
			name:   "legacy multiple keys AND",
			legacy: []string{"$browser=Chrome", "plan=enterprise"},
			want: []filterShape{
				{Key: "$browser", Operator: events.OpExact, Values: []string{"Chrome"}},
				{Key: "plan", Operator: events.OpExact, Values: []string{"enterprise"}},
			},
		},
		{
			name:   "legacy same key OR grouped",
			legacy: []string{"$browser=Chrome", "$browser=Firefox"},
			want:   []filterShape{{Key: "$browser", Operator: events.OpExact, Values: []string{"Chrome", "Firefox"}}},
		},
		{
			name:   "legacy missing equals skipped",
			legacy: []string{"$browser", "plan=free"},
			want:   []filterShape{{Key: "plan", Operator: events.OpExact, Values: []string{"free"}}},
		},
		{
			name:   "legacy all malformed returns nil",
			legacy: []string{"=foo", "bar"},
			want:   nil,
		},
		{
			name:           "json single icontains",
			propertiesJSON: `[{"key":"$current_url","operator":"icontains","value":"checkout"}]`,
			want:           []filterShape{{Key: "$current_url", Operator: events.OpIContains, Values: []string{"checkout"}}},
		},
		{
			name:           "json array value preserves order",
			propertiesJSON: `[{"key":"$browser","operator":"exact","value":["Chrome","Firefox"]}]`,
			want:           []filterShape{{Key: "$browser", Operator: events.OpExact, Values: []string{"Chrome", "Firefox"}}},
		},
		{
			name:           "json numeric value not reformatted",
			propertiesJSON: `[{"key":"count","operator":"gt","value":1000000}]`,
			want:           []filterShape{{Key: "count", Operator: events.OpGreaterThan, Values: []string{"1000000"}}},
		},
		{
			name:           "json is_set has no values",
			propertiesJSON: `[{"key":"$browser","operator":"is_set"}]`,
			want:           []filterShape{{Key: "$browser", Operator: events.OpIsSet, Values: nil}},
		},
		{
			name:           "json null value yields nil values",
			propertiesJSON: `[{"key":"$browser","operator":"exact","value":null}]`,
			want:           []filterShape{{Key: "$browser", Operator: events.OpExact, Values: nil}},
		},
		{
			name:           "json entry missing key skipped",
			propertiesJSON: `[{"operator":"exact","value":"x"},{"key":"plan","operator":"exact","value":"free"}]`,
			want:           []filterShape{{Key: "plan", Operator: events.OpExact, Values: []string{"free"}}},
		},
		{
			name:           "json entry missing operator skipped",
			propertiesJSON: `[{"key":"plan","value":"free"}]`,
			want:           nil,
		},
		{
			name:           "malformed json ignored",
			propertiesJSON: `not json`,
			want:           nil,
		},
		{
			name:           "malformed json ignored but legacy still applies",
			propertiesJSON: `{ broken`,
			legacy:         []string{"plan=free"},
			want:           []filterShape{{Key: "plan", Operator: events.OpExact, Values: []string{"free"}}},
		},
		{
			name:           "json and legacy merged, json first",
			propertiesJSON: `[{"key":"$current_url","operator":"icontains","value":"checkout"}]`,
			legacy:         []string{"$browser=Chrome"},
			want: []filterShape{
				{Key: "$current_url", Operator: events.OpIContains, Values: []string{"checkout"}},
				{Key: "$browser", Operator: events.OpExact, Values: []string{"Chrome"}},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := parsePropertyFilters(tt.propertiesJSON, tt.legacy)
			assert.Equal(t, tt.want, shapesOf(got))
		})
	}
}

func restrictionsResponse(body string) *http.Response {
	return &http.Response{
		StatusCode: http.StatusOK,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     make(http.Header),
	}
}

func TestStreamEventsHandlerAppliesPropertyRestrictions(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"restricted_event_properties": ["email"], "restricted_person_properties": ["email"]}`))
	}))
	defer server.Close()
	viper.Set("jwt.authorization_url", server.URL)
	t.Cleanup(func() { viper.Set("jwt.authorization_url", "") })
	viper.Set("jwt.secret", "test-property-restrictions-secret")
	token := createJWTToken(auth.ExpectedScope, jwt.MapClaims{
		"team_id": 1, "api_token": "test-project-token", "user_id": 1, "organization_id": "test-organization",
	})
	e := echo.New()

	t.Run("refuses a filter on a restricted property", func(t *testing.T) {
		request := httptest.NewRequest(http.MethodGet, `/events?properties=[{"key":"email","operator":"icontains","value":"@example.com"}]`, nil)
		request.Header.Set("Authorization", "Bearer "+token)
		handler := StreamEventsHandler(e.Logger, make(chan events.Subscription, 1), make(chan events.Subscription, 1))
		var httpError *echo.HTTPError
		require.ErrorAs(t, handler(e.NewContext(request, httptest.NewRecorder())), &httpError)
		assert.Equal(t, http.StatusBadRequest, httpError.Code)
	})

	t.Run("hands the restrictions to the subscription", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		request := httptest.NewRequest(http.MethodGet, "/events?property=$browser=Chrome", nil).WithContext(ctx)
		request.Header.Set("Authorization", "Bearer "+token)
		subChan := make(chan events.Subscription, 1)
		done := make(chan error, 1)
		go func() {
			done <- StreamEventsHandler(e.Logger, subChan, make(chan events.Subscription, 1))(e.NewContext(request, httptest.NewRecorder()))
		}()
		subscription := <-subChan
		assert.True(t, subscription.Restrictions.Load().RestrictsEventProperty("email"))
		assert.True(t, subscription.Restrictions.Load().RestrictsPersonProperty("email"))
		cancel()
		require.NoError(t, <-done)
	})
}

func TestStreamEventsHandlerEndsStreamWhenRecheckRestrictsFilteredProperty(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		viper.Set("jwt.secret", "test-periodic-restriction-secret")
		viper.Set("jwt.authorization_url", "http://authorization.test")
		defer viper.Set("jwt.authorization_url", "")

		var calls atomic.Int32
		originalTransport := http.DefaultTransport
		http.DefaultTransport = roundTripFunc(func(request *http.Request) (*http.Response, error) {
			if calls.Add(1) == 1 {
				return restrictionsResponse(`{"restricted_event_properties": [], "restricted_person_properties": []}`), nil
			}
			return restrictionsResponse(`{"restricted_event_properties": ["email"], "restricted_person_properties": []}`), nil
		})
		defer func() { http.DefaultTransport = originalTransport }()

		request := httptest.NewRequest(http.MethodGet, "/events?property=email=hidden@example.com", nil)
		request.Header.Set("Authorization", "Bearer "+createJWTToken(auth.ExpectedScope, jwt.MapClaims{
			"team_id": 1, "api_token": "test-project-token",
		}))
		e := echo.New()
		subChan := make(chan events.Subscription, 1)
		unSubChan := make(chan events.Subscription, 1)
		done := make(chan error, 1)
		go func() {
			done <- StreamEventsHandler(e.Logger, subChan, unSubChan)(e.NewContext(request, httptest.NewRecorder()))
		}()

		subscription := <-subChan
		assert.Nil(t, subscription.Restrictions.Load())
		time.Sleep(30 * time.Second)

		require.NoError(t, <-done)
		assert.True(t, subscription.Restrictions.Load().RestrictsEventProperty("email"))
		assert.Equal(t, int32(2), calls.Load())
	})
}
