package core

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"time"
)

const maxLogLines = 100
const logFilePath = "posthog-hobby.log"

type LogBuffer struct {
	mu      sync.RWMutex
	lines   []string
	logFile *os.File
}

var globalLog = &LogBuffer{lines: make([]string, 0, maxLogLines)}

func GetLogger() *LogBuffer {
	return globalLog
}

func InitLogFile() error {
	f, err := os.OpenFile(logFilePath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return err
	}
	globalLog.mu.Lock()
	globalLog.logFile = f
	globalLog.mu.Unlock()
	globalLog.Info("=== PostHog Hobby Installer started at %s ===", time.Now().Format(time.RFC3339))
	return nil
}

func CloseLogFile() {
	globalLog.mu.Lock()
	defer globalLog.mu.Unlock()
	if globalLog.logFile != nil {
		_ = globalLog.logFile.Close()
		globalLog.logFile = nil
	}
}

func (l *LogBuffer) writeToBuffer(s string) {
	lines := strings.Split(s, "\n")
	for _, line := range lines {
		line = strings.TrimRight(line, "\r")
		if line == "" {
			continue
		}
		l.lines = append(l.lines, line)
		if len(l.lines) > maxLogLines {
			l.lines = l.lines[1:]
		}
	}
}

func (l *LogBuffer) writeToFile(s string) {
	if l.logFile != nil {
		_, _ = l.logFile.WriteString(s)
		if !strings.HasSuffix(s, "\n") {
			_, _ = l.logFile.WriteString("\n")
		}
	}
}

func (l *LogBuffer) Write(p []byte) (n int, err error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	s := string(p)
	l.writeToBuffer(s)
	l.writeToFile(s)
	return len(p), nil
}

func (l *LogBuffer) WriteString(s string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.writeToBuffer(s)
	l.writeToFile(s)
}

func (l *LogBuffer) Info(format string, args ...any) {
	msg := fmt.Sprintf(format, args...)
	if !strings.HasSuffix(msg, "\n") {
		msg += "\n"
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.writeToBuffer(msg)
	l.writeToFile("[INFO] " + msg)
}

func (l *LogBuffer) Debug(format string, args ...any) {
	msg := fmt.Sprintf(format, args...)
	if !strings.HasSuffix(msg, "\n") {
		msg += "\n"
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.writeToFile("[DEBUG] " + msg)
}

func (l *LogBuffer) GetLines(n int) []string {
	l.mu.RLock()
	defer l.mu.RUnlock()

	if n <= 0 || n > len(l.lines) {
		n = len(l.lines)
	}
	start := len(l.lines) - n
	if start < 0 {
		start = 0
	}
	result := make([]string, len(l.lines)-start)
	copy(result, l.lines[start:])
	return result
}

func (l *LogBuffer) Clear() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.lines = l.lines[:0]
}
