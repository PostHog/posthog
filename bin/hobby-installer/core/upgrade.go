package core

import (
	"fmt"
	"os"
	"strings"
	"time"
)

type UpgradeCheck struct {
	HasNamedVolumes        bool
	NeedsPostgresMigration bool
	NeedsStorageMigration  bool
	PostgresBackupFile     string
	StorageMigrationStatus string
}

func CheckUpgradeRequirements() (*UpgradeCheck, error) {
	check := &UpgradeCheck{}

	postgres, clickhouse := CheckDockerVolumes()
	check.HasNamedVolumes = postgres && clickhouse

	check.NeedsPostgresMigration = checkPostgres12InCompose()

	check.StorageMigrationStatus = ReadEnvValue("SESSION_RECORDING_STORAGE_MIGRATED_TO_SEAWEEDFS")
	check.NeedsStorageMigration = check.StorageMigrationStatus == ""

	return check, nil
}

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

	if !FileExists(backupFile) {
		return "", fmt.Errorf("backup file was not created")
	}

	info, err := os.Stat(backupFile)
	if err != nil {
		return "", err
	}
	if info.Size() < 1000 {
		_ = os.Remove(backupFile)
		return "", fmt.Errorf("backup file too small (%d bytes)", info.Size())
	}

	return backupFile, nil
}

func MigratePostgres12To15(backupFile string) error {
	if err := DockerComposeDown(); err != nil {
		return fmt.Errorf("failed to stop stack: %w", err)
	}

	// Ignore error, volume might not exist
	_ = DockerVolumeRemove("postgres-data")

	return nil
}

func RestorePostgres15(backupFile string) error {
	if err := DockerComposeUpDB(); err != nil {
		return fmt.Errorf("failed to start database: %w", err)
	}

	time.Sleep(20 * time.Second)

	if err := RestorePostgres(backupFile); err != nil {
		return fmt.Errorf("failed to restore backup: %w", err)
	}

	cmd, args := GetDockerComposeCommand()
	fullArgs := append(args, "exec", "-T", "db", "psql", "-U", "posthog", "-c", "ALTER USER posthog WITH PASSWORD 'posthog';")
	_, _ = RunCommand(cmd, fullArgs...) // Best-effort password reset

	return nil
}

func SetStorageMigrationStatus(status string) error {
	return AppendToEnv("SESSION_RECORDING_STORAGE_MIGRATED_TO_SEAWEEDFS", status)
}
