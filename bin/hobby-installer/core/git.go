package core

import (
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strings"
)

const posthogRepoURL = "https://github.com/PostHog/posthog.git"

func ClonePostHog() error {
	logger := GetLogger()

	if DirExists("posthog") {
		logger.WriteString("PostHog repository already exists\n")
		return nil
	}

	logger.WriteString("Cloning PostHog repository...\n")
	_, err := RunCommand("git", "clone", "--filter=blob:none", posthogRepoURL)
	if err == nil {
		logger.WriteString("Repository cloned successfully\n")
	}
	return err
}

func UpdatePostHog() error {
	logger := GetLogger()

	if !DirExists("posthog") {
		return ClonePostHog()
	}

	logger.WriteString("Fetching latest changes...\n")
	_, err := RunCommandWithDir("posthog", "git", "fetch", "--prune")
	if err != nil {
		return err
	}

	logger.WriteString("Pulling updates...\n")
	_, err = RunCommandWithDir("posthog", "git", "pull")
	return err
}

func CheckoutVersion(version string) error {
	logger := GetLogger()
	logger.Debug("CheckoutVersion called with version=%q", version)

	if !DirExists("posthog") {
		logger.Debug("posthog directory not found")
		return fmt.Errorf("posthog directory not found")
	}

	switch version {
	case "latest":
		logger.Debug("Checking out latest (HEAD of current branch)")
		return checkoutLatest()
	case "latest-release":
		logger.Debug("Checking out latest release tag")
		return checkoutLatestRelease()
	default:
		logger.Debug("Checking out specific version: %s", version)
		return checkoutSpecific(version)
	}
}

func checkoutLatest() error {
	if _, err := RunCommandWithDir("posthog", "git", "fetch", "origin"); err != nil {
		return err
	}

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

func checkoutLatestRelease() error {
	if _, err := RunCommandWithDir("posthog", "git", "fetch", "--tags"); err != nil {
		return err
	}

	out, err := RunCommandWithDir("posthog", "git", "describe", "--tags", "--abbrev=0")
	if err != nil {
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
	isCommit := regexp.MustCompile(`^[0-9a-f]{40}$`).MatchString(version)

	if isCommit {
		_, err := RunCommandWithDir("posthog", "git", "checkout", version)
		return err
	}

	if _, err := RunCommandWithDir("posthog", "git", "fetch", "--tags"); err != nil {
		return err
	}

	releaseTag := strings.TrimPrefix(version, "release-")
	_, err := RunCommandWithDir("posthog", "git", "checkout", releaseTag)
	return err
}

func GetCurrentCommit() (string, error) {
	out, err := RunCommandWithDir("posthog", "git", "rev-parse", "--short", "HEAD")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(out), nil
}

func CopyComposeFiles(version string) error {
	logger := GetLogger()
	logger.Debug("CopyComposeFiles version=%q", version)

	_ = os.Remove("docker-compose.yml") // Ignore error if file doesn't exist

	if err := copyFile("posthog/docker-compose.base.yml", "docker-compose.base.yml"); err != nil {
		logger.Debug("Failed to copy docker-compose.base.yml: %v", err)
		return err
	}

	return copyFileWithEnvSubst("posthog/docker-compose.hobby.yml", "docker-compose.yml", version)
}

func copyFileWithEnvSubst(src, dst, version string) error {
	logger := GetLogger()
	data, err := os.ReadFile(src)
	if err != nil {
		logger.Debug("Failed to read %s: %v", src, err)
		return err
	}

	content := string(data)

	registryURL := os.Getenv("REGISTRY_URL")
	if registryURL == "" {
		registryURL = ReadEnvValue("REGISTRY_URL")
	}
	if registryURL == "" {
		registryURL = "posthog/posthog"
	}

	if version == "" {
		version = "latest"
	}

	logger.Debug("copyFileWithEnvSubst: REGISTRY_URL=%q, POSTHOG_APP_TAG=%q", registryURL, version)

	content = strings.ReplaceAll(content, "${REGISTRY_URL}", registryURL)
	content = strings.ReplaceAll(content, "$REGISTRY_URL", registryURL)
	content = strings.ReplaceAll(content, "${POSTHOG_APP_TAG}", version)
	content = strings.ReplaceAll(content, "$POSTHOG_APP_TAG", version)

	return os.WriteFile(dst, []byte(content), 0644)
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, data, 0644)
}

func CreateComposeScripts() error {
	if err := os.MkdirAll("compose", 0755); err != nil {
		return err
	}

	startScript := `#!/bin/bash
./compose/wait
./bin/migrate
./bin/docker-server
`
	if err := os.WriteFile("compose/start", []byte(startScript), 0755); err != nil {
		return err
	}

	temporalScript := `#!/bin/bash
./bin/temporal-django-worker
`
	if err := os.WriteFile("compose/temporal-django-worker", []byte(temporalScript), 0755); err != nil {
		return err
	}

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

func SetupGit() error {
	logger := GetLogger()

	if _, err := exec.LookPath("git"); err == nil {
		logger.Debug("git already installed")
		return nil
	}

	logger.Debug("Installing git")
	cmd := exec.Command("apt", "install", "-y", "git")
	return cmd.Run()
}
