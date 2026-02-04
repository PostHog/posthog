package core

import (
	"fmt"
	"os"
	"strings"
	"testing"
)

type mockCmdRunner struct {
	calls     []string
	responses map[string]mockResponse
}

type mockResponse struct {
	output string
	err    error
}

func newMockRunner() *mockCmdRunner {
	return &mockCmdRunner{responses: make(map[string]mockResponse)}
}

func (m *mockCmdRunner) runCmdDir(dir string, name string, args ...string) (string, error) {
	key := fmt.Sprintf("%s:%s %s", dir, name, strings.Join(args, " "))
	m.calls = append(m.calls, key)
	if resp, ok := m.responses[key]; ok {
		return resp.output, resp.err
	}
	return "", nil
}

func (m *mockCmdRunner) runCmd(name string, args ...string) (string, error) {
	key := fmt.Sprintf(":%s %s", name, strings.Join(args, " "))
	m.calls = append(m.calls, key)
	if resp, ok := m.responses[key]; ok {
		return resp.output, resp.err
	}
	return "", nil
}

func (m *mockCmdRunner) on(key string, output string, err error) {
	m.responses[key] = mockResponse{output: output, err: err}
}

func (m *mockCmdRunner) assertCalled(t *testing.T, key string) {
	t.Helper()
	for _, call := range m.calls {
		if call == key {
			return
		}
	}
	t.Errorf("expected call %q not found in %v", key, m.calls)
}

func (m *mockCmdRunner) assertNotCalled(t *testing.T, key string) {
	t.Helper()
	for _, call := range m.calls {
		if call == key {
			t.Errorf("unexpected call %q found in %v", key, m.calls)
			return
		}
	}
}

func setupMock(t *testing.T, m *mockCmdRunner) func() {
	t.Helper()
	origRunCmd := runCmd
	origRunCmdDir := runCmdDir
	runCmd = m.runCmd
	runCmdDir = m.runCmdDir
	return func() {
		runCmd = origRunCmd
		runCmdDir = origRunCmdDir
	}
}

func setupPosthogDir(t *testing.T) func() {
	t.Helper()
	origDir, _ := os.Getwd()
	tmpDir := t.TempDir()
	if err := os.Chdir(tmpDir); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll("posthog", 0755); err != nil {
		t.Fatal(err)
	}
	return func() {
		if err := os.Chdir(origDir); err != nil {
			t.Log(err)
		}
	}
}

func TestUpdatePostHog(t *testing.T) {
	t.Run("on branch pulls successfully", func(t *testing.T) {
		cleanupDir := setupPosthogDir(t)
		defer cleanupDir()

		mock := newMockRunner()
		mock.on("posthog:git branch --show-current", "master\n", nil)
		cleanupMock := setupMock(t, mock)
		defer cleanupMock()

		err := UpdatePostHog()
		if err != nil {
			t.Fatalf("expected no error, got: %v", err)
		}

		mock.assertCalled(t, "posthog:git fetch --prune")
		mock.assertCalled(t, "posthog:git pull")
	})

	t.Run("detached HEAD skips pull", func(t *testing.T) {
		cleanupDir := setupPosthogDir(t)
		defer cleanupDir()

		mock := newMockRunner()
		mock.on("posthog:git branch --show-current", "", nil)
		cleanupMock := setupMock(t, mock)
		defer cleanupMock()

		err := UpdatePostHog()
		if err != nil {
			t.Fatalf("expected no error on detached HEAD, got: %v", err)
		}

		mock.assertCalled(t, "posthog:git fetch --prune")
		mock.assertCalled(t, "posthog:git branch --show-current")
		mock.assertNotCalled(t, "posthog:git pull")
	})

	t.Run("no posthog dir triggers clone", func(t *testing.T) {
		origDir, _ := os.Getwd()
		tmpDir := t.TempDir()
		if err := os.Chdir(tmpDir); err != nil {
			t.Fatal(err)
		}
		defer func() { _ = os.Chdir(origDir) }()

		mock := newMockRunner()
		mock.on(":git clone --filter=blob:none https://github.com/PostHog/posthog.git", "", fmt.Errorf("clone failed"))
		cleanupMock := setupMock(t, mock)
		defer cleanupMock()

		err := UpdatePostHog()
		if err == nil {
			t.Fatal("expected clone error")
		}
		mock.assertCalled(t, ":git clone --filter=blob:none https://github.com/PostHog/posthog.git")
		mock.assertNotCalled(t, "posthog:git fetch --prune")
	})
}

func TestCheckoutVersion(t *testing.T) {
	t.Run("specific commit SHA", func(t *testing.T) {
		cleanupDir := setupPosthogDir(t)
		defer cleanupDir()

		mock := newMockRunner()
		cleanupMock := setupMock(t, mock)
		defer cleanupMock()

		sha := "abc123def456abc123def456abc123def456abc1"
		err := CheckoutVersion(sha)
		if err != nil {
			t.Fatalf("expected no error, got: %v", err)
		}
		mock.assertCalled(t, fmt.Sprintf("posthog:git checkout %s", sha))
	})

	t.Run("latest resets to origin branch", func(t *testing.T) {
		cleanupDir := setupPosthogDir(t)
		defer cleanupDir()

		mock := newMockRunner()
		mock.on("posthog:git branch --show-current", "master\n", nil)
		cleanupMock := setupMock(t, mock)
		defer cleanupMock()

		err := CheckoutVersion("latest")
		if err != nil {
			t.Fatalf("expected no error, got: %v", err)
		}
		mock.assertCalled(t, "posthog:git fetch origin")
		mock.assertCalled(t, "posthog:git reset --hard origin/master")
	})

	t.Run("no posthog dir returns error", func(t *testing.T) {
		origDir, _ := os.Getwd()
		tmpDir := t.TempDir()
		if err := os.Chdir(tmpDir); err != nil {
			t.Fatal(err)
		}
		defer func() { _ = os.Chdir(origDir) }()

		mock := newMockRunner()
		cleanupMock := setupMock(t, mock)
		defer cleanupMock()

		err := CheckoutVersion("latest")
		if err == nil {
			t.Fatal("expected error when posthog dir doesn't exist")
		}
	})
}
