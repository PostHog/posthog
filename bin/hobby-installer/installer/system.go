package installer

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
)

// Used to generate a random secret for POSTHOG_SECRET
func GenerateSecret() (string, error) {
	b := make([]byte, 28)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	hash := sha256.Sum224(b)
	return hex.EncodeToString(hash[:]), nil
}

// Used to generate a 32-byte hex key for ENCRYPTION_SALT_KEYS
func GenerateEncryptionKey() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// Run a shell command and return output as a string
func RunCommand(name string, args ...string) (string, error) {
	log := GetLogger()
	log.WriteString(fmt.Sprintf("$ %s %s\n", name, strings.Join(args, " ")))

	cmd := exec.Command(name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = io.MultiWriter(&stdout, log)
	cmd.Stderr = io.MultiWriter(&stderr, log)
	err := cmd.Run()
	if err != nil {
		return "", fmt.Errorf("%s: %s", err.Error(), stderr.String())
	}
	return stdout.String(), nil
}

// Run a command in a specific directory
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
		return "", fmt.Errorf("%s: %s", err.Error(), stderr.String())
	}
	return stdout.String(), nil
}

// Run a command and stream output in real-time
func RunCommandStreaming(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
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

func ReadEnvValue(key string) string {
	data, err := os.ReadFile(".env")
	if err != nil {
		return ""
	}
	lines := strings.Split(string(data), "\n")
	for _, line := range lines {
		if strings.HasPrefix(line, key+"=") {
			value := strings.TrimPrefix(line, key+"=")
			value = strings.Trim(value, "\"'")
			return value
		}
	}
	return ""
}

func AppendToEnv(key, value string) error {
	f, err := os.OpenFile(".env", os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()

	_, err = f.WriteString(fmt.Sprintf("%s=%s\n", key, value))
	return err
}
