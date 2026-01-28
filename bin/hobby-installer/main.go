package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/posthog/posthog/bin/hobby-installer/ci"
	"github.com/posthog/posthog/bin/hobby-installer/core"
	"github.com/posthog/posthog/bin/hobby-installer/tui"
)

type config struct {
	ciMode  bool
	version string
	domain  string
}

func parseArgs() config {
	ciFlag := flag.Bool("ci", false, "Run in non-interactive CI mode")
	version := flag.String("version", "latest", "PostHog version to install")
	domain := flag.String("domain", "", "Domain where PostHog will be accessible")
	flag.Parse()

	return config{
		ciMode:  *ciFlag || isCIEnvironment(),
		version: *version,
		domain:  *domain,
	}
}

func isCIEnvironment() bool {
	ciEnvVars := []string{"CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "CIRCLECI", "TRAVIS"}
	for _, v := range ciEnvVars {
		if os.Getenv(v) != "" {
			return true
		}
	}
	return false
}

func runCI(cfg config) error {
	domain := cfg.domain
	if domain == "" {
		domain = core.GetExistingDomain()
	}
	if domain == "" {
		return fmt.Errorf("--domain is required in CI mode (or set DOMAIN in .env)")
	}

	return ci.Run(ci.Config{
		Version: cfg.version,
		Domain:  domain,
	})
}

func runTUI() error {
	return tui.Run()
}

func main() {
	defer core.CloseTelemetry()
	if err := core.InitLogFile(); err != nil {
		fmt.Fprintf(os.Stderr, "Warning: could not create log file: %v\n", err)
	}
	defer core.CloseLogFile()

	cfg := parseArgs()

	var err error
	if cfg.ciMode {
		err = runCI(cfg)
	} else {
		err = runTUI()
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
