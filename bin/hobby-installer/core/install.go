package core

import (
	"fmt"
	"time"
)

type InstallStatus int

const (
	InstallPending InstallStatus = iota
	InstallRunning
	InstallSuccess
	InstallFailed
	InstallSkipped
)

type InstallResult struct {
	Err    error
	Detail string
}

type InstallConfig struct {
	IsUpgrade bool
	Version   string
	Domain    string
}

type InstallStep struct {
	Name   string
	Run    func(cfg InstallConfig) InstallResult
	Skip   func(cfg InstallConfig) (bool, string)
	Hidden bool
}

func GetInstallSteps() []InstallStep {
	return []InstallStep{
		{
			Name: "Send telemetry",
			Run: func(cfg InstallConfig) InstallResult {
				SendInstallStartEvent(cfg.Domain)
				return InstallResult{Detail: "sent"}
			},
			Hidden: true,
		},
		{
			Name: "Setup git",
			Run: func(cfg InstallConfig) InstallResult {
				_ = AptUpdate()
				if err := SetupGit(); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "git ready"}
			},
		},
		{
			Name: "Clone/update PostHog repository",
			Run: func(cfg InstallConfig) InstallResult {
				if DirExists("posthog") {
					if err := UpdatePostHog(); err != nil {
						return InstallResult{Err: err}
					}
					return InstallResult{Detail: "updated"}
				}
				if err := ClonePostHog(); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "cloned"}
			},
		},
		{
			Name: "Checkout version",
			Run: func(cfg InstallConfig) InstallResult {
				if err := CheckoutVersion(cfg.Version); err != nil {
					return InstallResult{Err: err}
				}
				commit, _ := GetCurrentCommit()
				return InstallResult{Detail: fmt.Sprintf("at %s", commit)}
			},
		},
		{
			Name: "Generate configuration",
			Run: func(cfg InstallConfig) InstallResult {
				if FileExists(".env") {
					if err := FixEnvQuoting(); err != nil {
						GetLogger().WriteString(fmt.Sprintf("Warning: could not fix .env quoting: %v\n", err))
					}
					if err := UpdateEnvForUpgrade(cfg.Version); err != nil {
						return InstallResult{Err: err}
					}
					return InstallResult{Detail: "updated"}
				}
				config, err := NewEnvConfig(cfg.Domain, cfg.Version)
				if err != nil {
					return InstallResult{Err: err}
				}
				if err := config.WriteEnvFile(); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "created .env"}
			},
		},
		{
			Name: "Download GeoIP database",
			Run: func(cfg InstallConfig) InstallResult {
				if GeoIPExists() {
					return InstallResult{Detail: "already exists"}
				}
				if err := DownloadGeoIP(); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "downloaded"}
			},
		},
		{
			Name: "Create startup scripts",
			Run: func(cfg InstallConfig) InstallResult {
				if err := CreateComposeScripts(); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "created"}
			},
		},
		{
			Name: "Copy Docker Compose files",
			Run: func(cfg InstallConfig) InstallResult {
				if err := CopyComposeFiles(cfg.Version); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "copied"}
			},
		},
		{
			Name: "Setup Docker",
			Run: func(cfg InstallConfig) InstallResult {
				if IsDockerInstalled() && IsDockerRunning() {
					return InstallResult{Detail: "Docker ready"}
				}

				if !IsDockerInstalled() {
					if err := InstallDocker(); err != nil {
						return InstallResult{Err: err}
					}
					if err := InstallDockerCompose(); err != nil {
						return InstallResult{Err: err}
					}
					return InstallResult{Detail: "installed"}
				}

				if !IsDockerRunning() {
					// Docker installed but not running - try to start it
					if err := StartDockerDaemon(); err != nil {
						return InstallResult{Err: err}
					}

					return InstallResult{Detail: "daemon started"}
				}

				return InstallResult{Detail: "Docker ready"}
			},
		},
		{
			Name: "Pull Docker images",
			Run: func(cfg InstallConfig) InstallResult {
				if err := DockerComposePull(); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "images pulled"}
			},
		},
		{
			Name: "Check async migrations",
			Run: func(cfg InstallConfig) InstallResult {
				hasPostgres, hasClickhouse := CheckDockerVolumes()
				if hasPostgres || hasClickhouse {
					if err := RunAsyncMigrationsCheck(); err != nil {
						return InstallResult{Err: err}
					}
					return InstallResult{Detail: "checked"}
				}
				return InstallResult{Detail: "skipped (new install)"}
			},
			Skip: func(cfg InstallConfig) (bool, string) {
				hasPostgres, hasClickhouse := CheckDockerVolumes()
				if !hasPostgres && !hasClickhouse {
					return true, "new install"
				}
				return false, ""
			},
		},
		{
			Name: "Start PostHog stack",
			Run: func(cfg InstallConfig) InstallResult {
				_ = DockerComposeStop()
				if err := DockerComposeUpWithRetry(3); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "started"}
			},
		},
		{
			Name: "Wait for PostHog to be ready",
			Run: func(cfg InstallConfig) InstallResult {
				if err := WaitForHealth(10 * time.Minute); err != nil {
					return InstallResult{Err: err}
				}
				return InstallResult{Detail: "PostHog is up!"}
			},
		},
		{
			Name: "Send completion telemetry",
			Run: func(cfg InstallConfig) InstallResult {
				SendInstallCompleteEvent(cfg.Domain)
				return InstallResult{Detail: "sent"}
			},
			Hidden: true,
		},
	}
}
