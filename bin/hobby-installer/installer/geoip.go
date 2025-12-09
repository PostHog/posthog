package installer

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
	// Create share directory
	if err := os.MkdirAll(shareDir, 0755); err != nil {
		return fmt.Errorf("failed to create share directory: %w", err)
	}

	// Check if already exists
	if FileExists(mmdbFile) {
		return nil
	}

	// Install required tools if needed
	if err := installGeoIPDeps(); err != nil {
		return err
	}

	// Download and decompress
	cmd := exec.Command("sh", "-c",
		fmt.Sprintf("curl -L '%s' --http1.1 | brotli --decompress --output=%s", geoIPURL, mmdbFile))
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("failed to download GeoIP database: %w", err)
	}

	// Create JSON metadata file
	jsonContent := fmt.Sprintf(`{"date": "%s"}`, time.Now().Format("2006-01-02"))
	if err := os.WriteFile(jsonFile, []byte(jsonContent), 0644); err != nil {
		return fmt.Errorf("failed to write GeoIP metadata: %w", err)
	}

	// Set permissions
	os.Chmod(mmdbFile, 0644)
	os.Chmod(jsonFile, 0644)

	return nil
}

func installGeoIPDeps() error {
	// Check if brotli is installed
	if _, err := exec.LookPath("brotli"); err == nil {
		return nil
	}

	// Install brotli
	cmd := exec.Command("sudo", "apt-get", "install", "-y", "--no-install-recommends", "brotli")
	return cmd.Run()
}

func GeoIPExists() bool {
	return FileExists(mmdbFile)
}
