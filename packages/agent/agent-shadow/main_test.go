package main

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) Do(request *http.Request) (*http.Response, error) {
	return fn(request)
}

func TestObserveReadyContract(t *testing.T) {
	client := roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode: http.StatusOK,
			Body: io.NopCloser(strings.NewReader(`{
                "hasSession": true,
                "readiness": "ready",
                "boot": {
                    "contractVersion": 1,
                    "bootId": "run-1",
                    "state": "ready",
                    "totalMs": 1200,
                    "phasesMs": {"acp_initialize": 300, "secret_phase": 99}
                }
            }`)),
		}, nil
	})
	now := time.Unix(10, 0)
	result := observe(context.Background(), client, config{
		BootID: "run-1", PollInterval: time.Millisecond,
	}, func() time.Time { return now })

	if result.Outcome != "ready" || result.ProductionMS != 1200 {
		t.Fatalf("unexpected result: %#v", result)
	}
	if _, present := result.PhasesMS["secret_phase"]; present {
		t.Fatal("non-allowlisted phase leaked into comparison record")
	}
}

func TestObserveIgnoresMismatchedBoot(t *testing.T) {
	client := roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{
			StatusCode: http.StatusOK,
			Body: io.NopCloser(strings.NewReader(`{
                "hasSession": true,
                "readiness": "ready",
                "boot": {"contractVersion": 1, "bootId": "another-run"}
            }`)),
		}, nil
	})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Millisecond)
	defer cancel()
	result := observe(ctx, client, config{
		BootID: "run-1", PollInterval: time.Millisecond,
	}, time.Now)

	if result.FailureClass != "timeout" {
		t.Fatalf("expected timeout, got %#v", result)
	}
}

func TestObserveTimesOutWithoutCopyingErrors(t *testing.T) {
	client := roundTripFunc(func(*http.Request) (*http.Response, error) {
		return nil, context.DeadlineExceeded
	})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Millisecond)
	defer cancel()
	result := observe(ctx, client, config{
		BootID: "run-1", PollInterval: time.Millisecond,
	}, time.Now)

	if result.FailureClass != "timeout" {
		t.Fatalf("expected timeout, got %#v", result)
	}
}
