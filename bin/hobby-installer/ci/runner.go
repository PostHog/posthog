package ci

import (
	"fmt"

	"github.com/posthog/posthog/bin/hobby-installer/core"
)

type Config struct {
	Version string
	Domain  string
}

func Run(cfg Config) error {
	isUpgrade := core.DirExists("posthog")

	if isUpgrade {
		fmt.Println("🔄 Upgrading PostHog")
	} else {
		fmt.Println("🚀 Installing PostHog")
	}
	fmt.Printf("   Version: %s\n", cfg.Version)
	fmt.Printf("   Domain:  %s\n", cfg.Domain)
	fmt.Println()

	if err := runChecks(); err != nil {
		return err
	}

	installCfg := core.InstallConfig{
		IsUpgrade: isUpgrade,
		Version:   cfg.Version,
		Domain:    cfg.Domain,
	}

	if err := runInstall(installCfg); err != nil {
		return err
	}

	fmt.Println()
	fmt.Println("✅ Installation complete!")
	fmt.Printf("   PostHog is running at: https://%s\n", cfg.Domain)
	return nil
}

func runChecks() error {
	fmt.Println("📋 Running system checks...")

	checks := core.GetChecks()
	hasErrors := false
	hasWarnings := false

	for _, check := range checks {
		fmt.Printf("   ○ %s... ", check.Name)
		result := check.Run()

		if result.Err != nil {
			fmt.Printf("✗ %s\n", result.Err)
			hasErrors = true
		} else if result.Warning {
			fmt.Printf("⚠ %s\n", result.Detail)
			hasWarnings = true
		} else {
			fmt.Printf("✓ %s\n", result.Detail)
		}
	}

	if hasErrors {
		return fmt.Errorf("system requirements not met")
	}

	if hasWarnings {
		fmt.Println("   ⚠ Some checks have warnings, proceeding anyway in CI mode")
	}

	fmt.Println()
	return nil
}

func runInstall(cfg core.InstallConfig) error {
	fmt.Println("📦 Installing PostHog...")

	steps := core.GetInstallSteps()

	for _, step := range steps {
		if step.Skip != nil {
			if skip, reason := step.Skip(cfg); skip {
				if !step.Hidden {
					fmt.Printf("   ○ %s... ◌ %s\n", step.Name, reason)
				}
				continue
			}
		}

		if !step.Hidden {
			fmt.Printf("   ○ %s... ", step.Name)
		}
		result := step.Run(cfg)

		if result.Err != nil {
			if !step.Hidden {
				fmt.Printf("✗ %s\n", result.Err)
			}
			return fmt.Errorf("%s failed: %w", step.Name, result.Err)
		}

		if !step.Hidden {
			fmt.Printf("✓ %s\n", result.Detail)
		}
	}

	return nil
}
