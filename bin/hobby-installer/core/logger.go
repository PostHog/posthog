package core

import (
	"io"
	"strings"
	"sync"
)

const maxLogLines = 100

type LogBuffer struct {
	mu    sync.RWMutex
	lines []string
}

var globalLog = &LogBuffer{lines: make([]string, 0, maxLogLines)}

func GetLogger() *LogBuffer {
	return globalLog
}

func (l *LogBuffer) Write(p []byte) (n int, err error) {
	l.mu.Lock()
	defer l.mu.Unlock()

	text := string(p)
	newLines := strings.Split(text, "\n")

	for _, line := range newLines {
		line = strings.TrimRight(line, "\r")
		if line == "" {
			continue
		}
		l.lines = append(l.lines, line)
		if len(l.lines) > maxLogLines {
			l.lines = l.lines[1:]
		}
	}
	return len(p), nil
}

func (l *LogBuffer) WriteString(s string) {
	_, _ = io.WriteString(l, s)
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
