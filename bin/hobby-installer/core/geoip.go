package core

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/andybalholm/brotli"
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

	if err := os.MkdirAll(shareDir, 0o755); err != nil {
		logger.Debug("Failed to create share directory: %v", err)
		return fmt.Errorf("failed to create share directory: %w", err)
	}

	if FileExists(mmdbFile) {
		logger.Debug("GeoIP database already exists at %s", mmdbFile)
		logger.WriteString("GeoIP database already exists\n")
		return nil
	}

	logger.WriteString("Downloading GeoIP database...\n")
	if err := DownloadDB(geoIPURL, mmdbFile); err != nil {
		return err
	}
	logger.WriteString("GeoIP database downloaded\n")

	jsonContent := fmt.Sprintf(`{"date": "%s"}`, time.Now().Format("2006-01-02"))
	if err := os.WriteFile(jsonFile, []byte(jsonContent), 0o644); err != nil {
		logger.Debug("Failed to write GeoIP metadata: %v", err)
		return fmt.Errorf("failed to write GeoIP metadata: %w", err)
	}

	if err := os.Chmod(mmdbFile, 0o644); err != nil {
		return fmt.Errorf("failed to set permissions on GeoIP database: %w", err)
	}
	if err := os.Chmod(jsonFile, 0o644); err != nil {
		return fmt.Errorf("failed to set permissions on GeoIP metadata: %w", err)
	}

	return nil
}

func DownloadDB(url, dest string) error {
	logger := GetLogger()
	logger.Debug("Downloading from %s", url)

	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Get(url)
	if err != nil {
		logger.Debug("Download failed: %v", err)
		return fmt.Errorf("failed to download %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("failed to download %s: HTTP %d", url, resp.StatusCode)
	}

	outFile, err := os.Create(dest)
	if err != nil {
		return fmt.Errorf("failed to create file %s: %w", dest, err)
	}
	defer outFile.Close()

	reader := brotli.NewReader(resp.Body)
	if _, err := io.Copy(outFile, reader); err != nil {
		os.Remove(dest)
		logger.Debug("Decompression failed: %v", err)
		return fmt.Errorf("failed to decompress %s: %w", dest, err)
	}

	return nil
}

func GeoIPExists() bool {
	return FileExists(mmdbFile)
}
