package core

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

func IsRoot() bool {
	return os.Geteuid() == 0
}

func RequireRoot(operation string) error {
	if !IsRoot() {
		return fmt.Errorf("root access required to %s. Please run this installer with sudo", operation)
	}
	return nil
}

func IsDockerInstalled() bool {
	_, err := exec.LookPath("docker")
	return err == nil
}

func IsDockerRunning() bool {
	cmd := exec.Command("docker", "info")
	return cmd.Run() == nil
}

func StartDockerDaemon() error {
	if err := RequireRoot("start Docker daemon"); err != nil {
		return err
	}

	GetLogger().WriteString("Starting Docker daemon...\n")
	cmd := exec.Command("systemctl", "start", "docker")

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("failed to start docker daemon: %w", err)
	}

	// Wait up to a minute for daemon to be ready
	GetLogger().WriteString("Waiting for Docker daemon to start...\n")
	for i := 0; i < 60; i++ {
		if IsDockerRunning() {
			GetLogger().WriteString("Docker daemon started\n")
			return nil
		}
		time.Sleep(1 * time.Second)
	}

	return fmt.Errorf("docker daemon started but not responding. Maybe you need to run this with sudo to access the Docker daemon?")
}

func InstallDocker() error {
	if err := RequireRoot("install Docker"); err != nil {
		return err
	}

	GetLogger().WriteString("Installing Docker...\n")

	commands := [][]string{
		{"apt", "update"},
		{"apt", "install", "-y", "apt-transport-https", "ca-certificates", "curl", "software-properties-common"},
		{"sh", "-c", "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -"},
		{"add-apt-repository", "-y", "deb [arch=amd64] https://download.docker.com/linux/ubuntu jammy stable"},
		{"apt", "update"},
		{"apt", "install", "-y", "docker-ce"},
	}

	for _, cmdArgs := range commands {
		cmd := exec.Command(cmdArgs[0], cmdArgs[1:]...)
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("failed to run %v: %w", cmdArgs, err)
		}
	}

	if err := AddCurrentUserToDockerGroup(); err != nil {
		GetLogger().WriteString("Warning: could not add user to docker group\n")
	}

	return nil
}

func InstallDockerCompose() error {
	if err := RequireRoot("install Docker Compose"); err != nil {
		return err
	}

	cmd := exec.Command("sh", "-c",
		`curl -L "https://github.com/docker/compose/releases/download/v2.33.1/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && chmod +x /usr/local/bin/docker-compose`)
	return cmd.Run()
}

func GetDockerComposeCommand() (string, []string) {
	if _, err := exec.LookPath("docker-compose"); err == nil {
		return "docker-compose", nil
	}
	return "docker", []string{"compose"}
}

func DockerComposeStop() error {
	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "-f", "docker-compose.yml", "stop")

	_, err := RunCommand(cmd, fullArgs...)
	return err
}

func DockerComposeDown() error {
	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "-f", "docker-compose.yml", "down")
	_, err := RunCommand(cmd, fullArgs...)
	return err
}

func DockerComposePull() error {
	GetLogger().WriteString("Pulling Docker images (this may take a while)...\n")

	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "-f", "docker-compose.yml", "pull")
	_, err := RunCommand(cmd, fullArgs...)
	if err == nil {
		GetLogger().WriteString("All images pulled successfully\n")
	}
	return err
}

func DockerComposeUpWithRetry(maxAttempts int) error {
	logger := GetLogger()
	logger.WriteString("Starting PostHog containers...\n")

	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "-f", "docker-compose.yml", "up", "-d", "--no-build", "--pull", "always")

	var lastErr error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		logger.WriteString(fmt.Sprintf("Starting stack (attempt %d/%d)...\n", attempt, maxAttempts))
		_, err := RunCommand(cmd, fullArgs...)
		if err == nil {
			logger.WriteString("Stack started successfully\n")
			return nil
		}
		lastErr = err
		if attempt < maxAttempts {
			logger.WriteString("Failed to start stack, waiting 30s before retry...\n")
			time.Sleep(30 * time.Second)
		}
	}

	logger.WriteString(fmt.Sprintf("Failed to start stack after %d attempts\n", maxAttempts))
	return lastErr
}

func DockerComposeUpDB() error {
	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "-f", "docker-compose.yml", "up", "-d", "db")
	_, err := RunCommand(cmd, fullArgs...)
	return err
}

func RunAsyncMigrationsCheck() error {
	GetLogger().WriteString("Checking async migrations...\n")

	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "run", "asyncmigrationscheck")
	_, err := RunCommand(cmd, fullArgs...)
	return err
}

func WaitForHealth(timeout time.Duration) error {
	logger := GetLogger()
	logger.WriteString("Waiting for PostHog to start...\n")

	deadline := time.Now().Add(timeout)
	client := &http.Client{Timeout: 5 * time.Second}
	attempt := 0

	for time.Now().Before(deadline) {
		attempt++
		resp, err := client.Get("http://localhost/_health")
		if err == nil {
			_ = resp.Body.Close()
			if resp.StatusCode == 200 {
				logger.WriteString("PostHog is healthy!\n")
				return nil
			}
			logger.WriteString(fmt.Sprintf("Health check %d: status %d\n", attempt, resp.StatusCode))
		} else {
			logger.WriteString(fmt.Sprintf("Health check %d: waiting...\n", attempt))
		}

		if (attempt % 5) == 0 {
			logger.WriteString("Waiting for PostHog to be healthy, this might take several minutes...\n")
		}

		time.Sleep(5 * time.Second)
	}

	return fmt.Errorf("timeout waiting for PostHog to be healthy")
}

func CheckDockerVolumes() (bool, bool) {
	out, err := RunCommand("docker", "volume", "ls")
	if err != nil {
		return false, false
	}

	hasPostgres := strings.Contains(out, "postgres-data")
	hasClickhouse := strings.Contains(out, "clickhouse-data")

	return hasPostgres, hasClickhouse
}

func AddUserToDockerGroup(user string) error {
	if err := RequireRoot("add user to docker group"); err != nil {
		return err
	}
	return exec.Command("usermod", "-aG", "docker", user).Run()
}

func AddCurrentUserToDockerGroup() error {
	user := os.Getenv("SUDO_USER")
	if user == "" {
		user = os.Getenv("USER")
	}
	if user == "" || user == "root" {
		return fmt.Errorf("cannot find user to add to docker group")
	}
	return AddUserToDockerGroup(user)
}

func DockerVolumeRemove(name string) error {
	return exec.Command("docker", "volume", "rm", name).Run()
}

func DockerExec(container string, command ...string) (string, error) {
	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "exec", "-T", container)
	fullArgs = append(fullArgs, command...)
	return RunCommand(cmd, fullArgs...)
}

func BackupPostgres(outputFile string) error {
	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "exec", "-T", "db", "pg_dumpall", "--clean", "-U", "posthog")

	shellCmd := fmt.Sprintf("%s %s | gzip > %s", cmd, joinArgs(fullArgs), outputFile)
	return exec.Command("sh", "-c", shellCmd).Run()
}

func RestorePostgres(inputFile string) error {
	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "exec", "-T", "db", "psql", "-U", "posthog")

	shellCmd := fmt.Sprintf("gunzip -c %s | %s %s", inputFile, cmd, joinArgs(fullArgs))
	return exec.Command("sh", "-c", shellCmd).Run()
}

func joinArgs(args []string) string {
	result := ""
	for i, arg := range args {
		if i > 0 {
			result += " "
		}
		result += arg
	}
	return result
}
