package installer

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"
)

// UpgradeCheck holds the result of pre-upgrade checks
type UpgradeCheck struct {
	HasNamedVolumes        bool
	NeedsPostgresMigration bool
	NeedsStorageMigration  bool
	PostgresBackupFile     string
	StorageMigrationStatus string
}

func CheckUpgradeRequirements() (*UpgradeCheck, error) {
	check := &UpgradeCheck{}

	// Check for named volumes
	postgres, clickhouse := CheckDockerVolumes()
	check.HasNamedVolumes = postgres && clickhouse

	// Check for postgres 12 in compose file
	check.NeedsPostgresMigration = checkPostgres12InCompose()

	// Check storage migration status
	check.StorageMigrationStatus = ReadEnvValue("SESSION_RECORDING_STORAGE_MIGRATED_TO_SEAWEEDFS")
	check.NeedsStorageMigration = check.StorageMigrationStatus == ""

	return check, nil
}

// Returns warning message if named volumes are missing (pre-1.39 installation)
func GetVolumeWarning() string {
	postgres, clickhouse := CheckDockerVolumes()
	if postgres && clickhouse {
		return ""
	}

	return `WARNING: POTENTIAL DATA LOSS

We were unable to find named clickhouse and postgres volumes.
If you created your PostHog stack PRIOR TO August 12th, 2022 / v1.39.0,
the Postgres and Clickhouse containers did NOT have persistent named volumes by default.

If you choose to upgrade, you will likely lose data contained in these anonymous volumes.

See: https://github.com/PostHog/posthog/pull/11256

WE STRONGLY RECOMMEND YOU:
• Stop and back up your entire environment
• Back up /var/lib/postgresql/data in the postgres container
• Back up /var/lib/clickhouse in the clickhouse container`
}

func checkPostgres12InCompose() bool {
	data, err := os.ReadFile("posthog/docker-compose.hobby.yml")
	if err != nil {
		return false
	}

	content := string(data)
	return strings.Contains(content, "postgres:12-alpine") || strings.Contains(content, "postgres:12")
}

func BackupPostgres12() (string, error) {
	backupFile := fmt.Sprintf("backup_pg12_%s.sql.gz", time.Now().Format("20060102_150405"))

	if err := BackupPostgres(backupFile); err != nil {
		return "", fmt.Errorf("backup failed: %w", err)
	}

	// Verify backup
	if !FileExists(backupFile) {
		return "", fmt.Errorf("backup file was not created")
	}

	info, err := os.Stat(backupFile)
	if err != nil {
		return "", err
	}
	if info.Size() < 1000 {
		os.Remove(backupFile)
		return "", fmt.Errorf("backup file too small (%d bytes)", info.Size())
	}

	return backupFile, nil
}

func MigratePostgres12To15(backupFile string) error {
	if err := DockerComposeDown(); err != nil {
		return fmt.Errorf("failed to stop stack: %w", err)
	}

	if err := DockerVolumeRemove("postgres-data"); err != nil {
		// Ignore error, volume might not exist
	}

	return nil
}

func RestorePostgres15(backupFile string) error {
	// Start just the DB
	if err := DockerComposeUpDB(); err != nil {
		return fmt.Errorf("failed to start database: %w", err)
	}

	// Wait for DB to be ready
	time.Sleep(20 * time.Second)

	// Restore backup
	if err := RestorePostgres(backupFile); err != nil {
		return fmt.Errorf("failed to restore backup: %w", err)
	}

	// Upgrade password to SCRAM-SHA-256
	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "exec", "-T", "db", "psql", "-U", "posthog", "-c", "ALTER USER posthog WITH PASSWORD 'posthog';")
	RunCommand(cmd, fullArgs...)

	return nil
}

func FixEnvQuoting() error {
	data, err := os.ReadFile(".env")
	if err != nil {
		return nil // File doesn't exist, nothing to fix
	}

	var result strings.Builder
	scanner := bufio.NewScanner(strings.NewReader(string(data)))

	for scanner.Scan() {
		line := scanner.Text()

		// Skip empty lines and comments
		if strings.TrimSpace(line) == "" || strings.HasPrefix(strings.TrimSpace(line), "#") {
			result.WriteString(line)
			result.WriteString("\n")
			continue
		}

		// Split on first =
		idx := strings.Index(line, "=")
		if idx == -1 {
			result.WriteString(line)
			result.WriteString("\n")
			continue
		}

		key := strings.TrimSpace(line[:idx])
		value := strings.TrimSpace(line[idx+1:])

		// Already quoted?
		if (strings.HasPrefix(value, "\"") && strings.HasSuffix(value, "\"")) ||
			(strings.HasPrefix(value, "'") && strings.HasSuffix(value, "'")) {
			result.WriteString(line)
			result.WriteString("\n")
			continue
		}

		// Quote if contains space, comma, or ://
		needsQuote := strings.ContainsAny(value, " ,") || strings.Contains(value, "://")
		if needsQuote {
			value = strings.ReplaceAll(value, "\"", "\\\"")
			result.WriteString(fmt.Sprintf("%s=\"%s\"\n", key, value))
		} else {
			result.WriteString(line)
			result.WriteString("\n")
		}
	}

	return os.WriteFile(".env", []byte(result.String()), 0600)
}

// Validates the .env file has required keys
func ValidateEnvForUpgrade() error {
	required := []string{"POSTHOG_SECRET", "DOMAIN"}
	for _, key := range required {
		if ReadEnvValue(key) == "" {
			return fmt.Errorf("missing required env var: %s", key)
		}
	}

	// Validate encryption key format if present
	encKey := ReadEnvValue("ENCRYPTION_SALT_KEYS")
	if encKey != "" {
		// Should be 32 hex chars
		if !regexp.MustCompile(`^[A-Za-z0-9_-]{32}$`).MatchString(encKey) {
			return fmt.Errorf("ENCRYPTION_SALT_KEYS is not in correct format")
		}
	}

	return nil
}

func SetStorageMigrationStatus(status string) error {
	return AppendToEnv("SESSION_RECORDING_STORAGE_MIGRATED_TO_SEAWEEDFS", status)
}
