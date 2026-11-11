package core

import (
	"bytes"
	"crypto/rand"
	"crypto/sha512"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
)

func GenerateSecret() (string, error) {
	b := make([]byte, 48)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	hash := sha512.Sum384(b)
	return hex.EncodeToString(hash[:]), nil
}

func GenerateEncryptionKey() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func RunCommand(name string, args ...string) (string, error) {
	log := GetLogger()
	log.WriteString(fmt.Sprintf("$ %s %s\n", name, strings.Join(args, " ")))

	cmd := exec.Command(name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = io.MultiWriter(&stdout, log)
	cmd.Stderr = io.MultiWriter(&stderr, log)
	err := cmd.Run()
	if err != nil {
		log.Debug("Command failed: %s %s\nstderr: %s", name, strings.Join(args, " "), stderr.String())
		return "", fmt.Errorf("%s: %s", err.Error(), stderr.String())
	}
	log.Debug("Command succeeded: %s (stdout len=%d)", name, len(stdout.String()))
	return stdout.String(), nil
}

func RunCommandWithDir(dir string, name string, args ...string) (string, error) {
	log := GetLogger()
	log.WriteString(fmt.Sprintf("$ cd %s && %s %s\n", dir, name, strings.Join(args, " ")))

	cmd := exec.Command(name, args...)
	cmd.Dir = dir
	var stdout, stderr bytes.Buffer
	cmd.Stdout = io.MultiWriter(&stdout, log)
	cmd.Stderr = io.MultiWriter(&stderr, log)
	err := cmd.Run()
	if err != nil {
		log.Debug("Command failed in %s: %s %s\nstderr: %s", dir, name, strings.Join(args, " "), stderr.String())
		return "", fmt.Errorf("%s: %s", err.Error(), stderr.String())
	}
	log.Debug("Command succeeded in %s: %s (stdout len=%d)", dir, name, len(stdout.String()))
	return stdout.String(), nil
}

func FileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func DirExists(path string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return info.IsDir()
}

func AptUpdate() error {
	logger := GetLogger()

	logger.WriteString("Updating apt cache...\n")
	logger.Debug("Running apt update")

	cmd := exec.Command("apt", "update")
	return cmd.Run()
}

func ReadEnvValue(key string) string {
	data, err := os.ReadFile(".env")
	if err != nil {
		return ""
	}
	lines := strings.Split(string(data), "\n")
	value := ""
	for _, line := range lines {
		if strings.HasPrefix(line, key+"=") {
			value = strings.Trim(strings.TrimPrefix(line, key+"="), "\"'")
		}
	}
	return value
}

func AppendToEnv(key, value string) error {
	data, err := os.ReadFile(".env")
	if err != nil {
		return err
	}
	f, err := os.OpenFile(".env", os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()

	if len(data) > 0 && data[len(data)-1] != '\n' {
		if _, err := f.WriteString("\n"); err != nil {
			return err
		}
	}
	_, err = fmt.Fprintf(f, "%s=%s\n", key, value)
	return err
}
