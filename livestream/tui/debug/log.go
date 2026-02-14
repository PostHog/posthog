package debug

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

var (
	logFile *os.File
	mu      sync.Mutex
	enabled bool
)

func Init() error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	dir := filepath.Join(home, ".posthog")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	path := filepath.Join(dir, "livestream-debug.log")
	logFile, err = os.Create(path)
	if err != nil {
		return err
	}
	enabled = true
	Log("session", "debug log started")
	return nil
}

func Log(component, format string, args ...interface{}) {
	if !enabled {
		return
	}
	mu.Lock()
	defer mu.Unlock()
	ts := time.Now().Format("15:04:05.000")
	msg := fmt.Sprintf(format, args...)
	_, _ = fmt.Fprintf(logFile, "%s [%s] %s\n", ts, component, msg)
}

func Close() {
	if logFile != nil {
		_ = logFile.Close()
	}
}

func Path() string {
	if logFile != nil {
		return logFile.Name()
	}
	return ""
}
