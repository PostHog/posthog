package core

import (
	"fmt"
	"os/exec"
	"strconv"
	"strings"
)

type CheckStatus int

const (
	CheckPending CheckStatus = iota
	CheckRunning
	CheckPassed
	CheckFailed
	CheckWarning
)

type CheckResult struct {
	Passed  bool
	Warning bool
	Detail  string
	Err     error
}

type Check struct {
	Name string
	Run  func() CheckResult
}

func GetChecks() []Check {
	return []Check{
		{Name: "Docker installed", Run: checkDocker},
		{Name: "Docker Compose available", Run: checkDockerCompose},
		{Name: "Memory (8GB+ recommended)", Run: checkMemory},
		{Name: "Disk space available", Run: checkDiskSpace},
		{Name: "Network connectivity", Run: checkNetwork},
		{Name: "Docker volumes", Run: checkDockerVolumes},
	}
}

func checkDocker() CheckResult {
	logger := GetLogger()
	logger.WriteString("Checking for Docker...\n")

	_, err := exec.LookPath("docker")
	if err != nil {
		logger.WriteString("⚠ Docker not found, will be installed\n")
		return CheckResult{Passed: true, Warning: true, Detail: "not installed, will install"}
	}

	logger.WriteString("$ docker info\n")
	cmd := exec.Command("docker", "info")
	if err := cmd.Run(); err != nil {
		logger.WriteString("⚠ Docker daemon not running\n")
		return CheckResult{Passed: true, Warning: true, Detail: "daemon not running for this user, might need sudo to detect or add current user to `docker` group"}
	}

	logger.WriteString("✓ Docker is running\n")
	return CheckResult{Passed: true, Detail: "Docker is running"}
}

func checkDockerCompose() CheckResult {
	logger := GetLogger()
	logger.WriteString("Checking for Docker Compose...\n")

	_, err := exec.LookPath("docker-compose")
	if err == nil {
		logger.WriteString("✓ docker-compose available\n")
		return CheckResult{Passed: true, Detail: "docker-compose available"}
	}

	logger.WriteString("$ docker compose version\n")
	cmd := exec.Command("docker", "compose", "version")
	if err := cmd.Run(); err == nil {
		logger.WriteString("✓ docker compose available\n")
		return CheckResult{Passed: true, Detail: "docker compose available"}
	}

	logger.WriteString("⚠ Docker Compose not found, will be installed\n")
	return CheckResult{Passed: true, Warning: true, Detail: "not installed, will install"}
}

func checkMemory() CheckResult {
	logger := GetLogger()
	logger.WriteString("Checking system memory...\n")

	scale := int64(1024 * 1024)
	cmd := exec.Command("sh", "-c", "grep MemTotal /proc/meminfo | awk '{print $2}'")
	out, err := cmd.Output()
	logger.Debug("Memory check /proc/meminfo: out=%q, err=%v", strings.TrimSpace(string(out)), err)

	if err != nil || string(out) == "" {
		scale = int64(1024 * 1024 * 1024)
		logger.WriteString("$ sysctl -n hw.memsize\n")
		cmd = exec.Command("sysctl", "-n", "hw.memsize")
		out, err = cmd.Output()
		logger.Debug("Memory check sysctl: out=%q, err=%v", strings.TrimSpace(string(out)), err)

		if err != nil || string(out) == "" {
			logger.WriteString("⚠ Could not check memory\n")
			return CheckResult{Passed: true, Warning: true, Detail: "Could not check memory"}
		}
	}

	memKB, _ := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
	memGB := memKB / scale
	logger.Debug("Memory: raw=%d, scale=%d, GB=%d", memKB, scale, memGB)
	logger.WriteString(fmt.Sprintf("Memory: %dGB\n", memGB))

	if memGB < 8 {
		return CheckResult{Passed: true, Warning: true, Detail: fmt.Sprintf("%dGB (8GB+ recommended)", memGB)}
	}
	return CheckResult{Passed: true, Detail: fmt.Sprintf("%dGB available", memGB)}
}

func checkDiskSpace() CheckResult {
	logger := GetLogger()
	logger.WriteString("$ df -h .\n")

	cmd := exec.Command("df", "-h", ".")
	out, err := cmd.Output()
	if err != nil {
		logger.WriteString("⚠ Could not check disk space\n")
		return CheckResult{Passed: true, Warning: true, Detail: "Could not check disk space"}
	}

	lines := strings.Split(string(out), "\n")
	if len(lines) < 2 {
		return CheckResult{Passed: true, Warning: true, Detail: "Could not parse disk info"}
	}

	fields := strings.Fields(lines[1])
	if len(fields) >= 4 {
		available := fields[3]
		logger.WriteString(fmt.Sprintf("Disk available: %s\n", available))
		return CheckResult{Passed: true, Detail: fmt.Sprintf("%s available", available)}
	}

	return CheckResult{Passed: true, Detail: "OK"}
}

func checkNetwork() CheckResult {
	logger := GetLogger()
	logger.WriteString("$ curl -s https://github.com\n")

	cmd := exec.Command("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "5", "https://github.com")
	out, err := cmd.Output()
	httpCode := strings.TrimSpace(string(out))
	logger.Debug("Network check: http_code=%q, err=%v", httpCode, err)

	if err != nil || httpCode != "200" {
		logger.WriteString("✗ Cannot reach github.com\n")
		return CheckResult{Passed: false, Err: fmt.Errorf("cannot reach github.com")}
	}
	logger.WriteString("✓ Connected to github.com\n")
	return CheckResult{Passed: true, Detail: "Connected"}
}

func checkDockerVolumes() CheckResult {
	logger := GetLogger()

	if !DirExists("posthog") {
		logger.Debug("posthog directory not found, skipping volume check")
		logger.WriteString("New installation, skipping volume check\n")
		return CheckResult{Passed: true, Detail: "new install"}
	}

	logger.WriteString("Checking for named Docker volumes...\n")
	hasPostgres, hasClickhouse := CheckDockerVolumes()
	logger.Debug("Docker volumes: postgres=%v, clickhouse=%v", hasPostgres, hasClickhouse)

	if hasPostgres && hasClickhouse {
		logger.WriteString("✓ Named volumes found\n")
		return CheckResult{Passed: true, Detail: "postgres-data, clickhouse-data"}
	}

	warning := GetVolumeWarning()
	logger.Debug("Volume warning: %q", warning)
	if warning != "" {
		logger.WriteString("⚠ " + warning + "\n")
		return CheckResult{Passed: true, Warning: true, Detail: "volumes may be anonymous (pre-1.39)"}
	}

	return CheckResult{Passed: true, Detail: "OK"}
}
