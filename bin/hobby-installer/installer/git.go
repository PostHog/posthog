package installer

import (
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strings"
)

const posthogRepoURL = "https://github.com/PostHog/posthog.git"

func ClonePostHog() error {
	if DirExists("posthog") {
		return nil // Already cloned
	}

	_, err := RunCommand("git", "clone", posthogRepoURL)
	return err
}

// Updates the existing PostHog repository to the latest version
func UpdatePostHog() error {
	if !DirExists("posthog") {
		return ClonePostHog()
	}

	_, err := RunCommandWithDir("posthog", "git", "fetch", "--prune")
	if err != nil {
		return err
	}

	_, err = RunCommandWithDir("posthog", "git", "pull")
	return err
}

// CheckoutVersion checks out a specific version of PostHog
func CheckoutVersion(version string) error {
	if !DirExists("posthog") {
		return fmt.Errorf("posthog directory not found")
	}

	switch version {
	case "latest":
		return checkoutLatest()
	case "latest-release":
		return checkoutLatestRelease()
	default:
		return checkoutSpecific(version)
	}
}

func checkoutLatest() error {
	// Fetch and reset to origin/main or current branch
	if _, err := RunCommandWithDir("posthog", "git", "fetch", "origin"); err != nil {
		return err
	}

	// Get current branch
	branch, err := RunCommandWithDir("posthog", "git", "branch", "--show-current")
	if err != nil {
		return err
	}
	branch = strings.TrimSpace(branch)

	if branch != "" {
		_, err = RunCommandWithDir("posthog", "git", "reset", "--hard", "origin/"+branch)
	}
	return err
}

// Deprecated: we don't create new `latest-release` tags anymore
func checkoutLatestRelease() error {
	if _, err := RunCommandWithDir("posthog", "git", "fetch", "--tags"); err != nil {
		return err
	}

	// Get latest tag
	out, err := RunCommandWithDir("posthog", "git", "describe", "--tags", "--abbrev=0")
	if err != nil {
		// Fallback: get latest tag from rev-list
		out, err = RunCommandWithDir("posthog", "sh", "-c", "git describe --tags $(git rev-list --tags --max-count=1)")
		if err != nil {
			return fmt.Errorf("no release tags found")
		}
	}
	tag := strings.TrimSpace(out)

	_, err = RunCommandWithDir("posthog", "git", "checkout", tag)
	return err
}

func checkoutSpecific(version string) error {
	// Check if it's a commit hash (40 hex chars)
	isCommit := regexp.MustCompile(`^[0-9a-f]{40}$`).MatchString(version)

	if isCommit {
		_, err := RunCommandWithDir("posthog", "git", "checkout", version)
		return err
	}

	// It's a tag/branch
	if _, err := RunCommandWithDir("posthog", "git", "fetch", "--tags"); err != nil {
		return err
	}

	// Try stripping "release-" prefix if present
	releaseTag := strings.TrimPrefix(version, "release-")
	_, err := RunCommandWithDir("posthog", "git", "checkout", releaseTag)
	return err
}

// GetCurrentCommit returns the current commit hash
func GetCurrentCommit() (string, error) {
	out, err := RunCommandWithDir("posthog", "git", "rev-parse", "--short", "HEAD")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
}

// CopyComposeFiles copies docker-compose files to the working directory
func CopyComposeFiles() error {
	// Remove existing docker-compose.yml
	os.Remove("docker-compose.yml")

	// Copy base file
	if err := copyFile("posthog/docker-compose.base.yml", "docker-compose.base.yml"); err != nil {
		return err
	}

	// Copy hobby file
	return copyFile("posthog/docker-compose.hobby.yml", "docker-compose.yml")
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, data, 0644)
}

// CreateComposeScripts creates the compose/start and compose/wait scripts
func CreateComposeScripts() error {
	if err := os.MkdirAll("compose", 0755); err != nil {
		return err
	}

	// Create start script
	startScript := `#!/bin/bash
./compose/wait
./bin/migrate
./bin/docker-server
`
	if err := os.WriteFile("compose/start", []byte(startScript), 0755); err != nil {
		return err
	}

	// Create temporal-django-worker script
	temporalScript := `#!/bin/bash
./bin/temporal-django-worker
`
	if err := os.WriteFile("compose/temporal-django-worker", []byte(temporalScript), 0755); err != nil {
		return err
	}

	// Create wait script
	waitScript := `#!/usr/bin/env python3

import socket
import time

def loop():
    print("Waiting for ClickHouse and Postgres to be ready")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(('clickhouse', 9000))
        print("Clickhouse is ready")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(('db', 5432))
        print("Postgres is ready")
    except ConnectionRefusedError as e:
        time.sleep(5)
        loop()

loop()
`
	return os.WriteFile("compose/wait", []byte(waitScript), 0755)
}

// SetupGit installs git if needed
func SetupGit() error {
	if _, err := exec.LookPath("git"); err == nil {
		return nil // Already installed
	}
	// Install git
	cmd := exec.Command("sudo", "apt", "install", "-y", "git")
	return cmd.Run()
}
