package core

import (
	"fmt"
	"os"
	"os/exec"
	"time"
)

const (
	geoIPURL = "https://mmdbcdn.posthog.net/"
	shareDir = "./share"
	mmdbFile = "./share/GeoLite2-City.mmdb"
	jsonFile = "./share/GeoLite2-City.json"
)

func DownloadGeoIP() error {
	logger := GetLogger()
	logger.Debug("DownloadGeoIP: shareDir=%s, mmdbFile=%s", shareDir, mmdbFile)

	if err := os.MkdirAll(shareDir, 0755); err != nil {
		logger.Debug("Failed to create share directory: %v", err)
		return fmt.Errorf("failed to create share directory: %w", err)
	}

	if FileExists(mmdbFile) {
		logger.Debug("GeoIP database already exists at %s", mmdbFile)
		logger.WriteString("GeoIP database already exists\n")
		return nil
	}

	if err := installGeoIPDeps(); err != nil {
		logger.Debug("Failed to install GeoIP deps: %v", err)
		return err
	}

	logger.WriteString("Downloading GeoIP database...\n")
	logger.Debug("Downloading from %s", geoIPURL)
	cmd := exec.Command("sh", "-c",
		fmt.Sprintf("curl -L '%s' --http1.1 | brotli --decompress --output=%s", geoIPURL, mmdbFile))
	if err := cmd.Run(); err != nil {
		logger.Debug("GeoIP download failed: %v", err)
		return fmt.Errorf("failed to download GeoIP database: %w", err)
	}
	logger.WriteString("GeoIP database downloaded\n")

	jsonContent := fmt.Sprintf(`{"date": "%s"}`, time.Now().Format("2006-01-02"))
	if err := os.WriteFile(jsonFile, []byte(jsonContent), 0644); err != nil {
		logger.Debug("Failed to write GeoIP metadata: %v", err)
		return fmt.Errorf("failed to write GeoIP metadata: %w", err)
	}

	if err := os.Chmod(mmdbFile, 0644); err != nil {
		return fmt.Errorf("failed to set permissions on GeoIP database: %w", err)
	}
	if err := os.Chmod(jsonFile, 0644); err != nil {
		return fmt.Errorf("failed to set permissions on GeoIP metadata: %w", err)
	}

	return nil
}

func installGeoIPDeps() error {
	logger := GetLogger()

	if _, err := exec.LookPath("brotli"); err == nil {
		logger.Debug("brotli already installed")
		return nil
	}

	logger.Debug("Installing brotli")
	cmd := exec.Command("apt-get", "install", "-y", "--no-install-recommends", "brotli")
	return cmd.Run()
}

func GeoIPExists() bool {
	return FileExists(mmdbFile)
}
