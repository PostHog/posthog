package ui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// RenderLogPanel renders a panel showing log lines
func RenderLogPanel(lines []string, width, height int) string {
	if width < 20 {
		width = 100
	}
	if height < 3 {
		height = 6
	}

	innerWidth := width - 4
	innerHeight := height - 2

	if innerHeight < 1 {
		innerHeight = 1
	}

	// Trim lines to fit and take last N lines
	var displayLines []string
	for _, line := range lines {
		if len(line) > innerWidth-2 {
			line = line[:innerWidth-5] + "..."
		}
		displayLines = append(displayLines, line)
	}

	// Take last innerHeight lines
	if len(displayLines) > innerHeight {
		displayLines = displayLines[len(displayLines)-innerHeight:]
	}

	// Pad with empty lines if needed
	for len(displayLines) < innerHeight {
		displayLines = append([]string{""}, displayLines...)
	}

	content := strings.Join(displayLines, "\n")

	// Use lipgloss NormalBorder (ASCII: +, -, |)
	panel := lipgloss.NewStyle().
		Border(lipgloss.NormalBorder()).
		BorderForeground(ColorMuted).
		Foreground(ColorMuted).
		Width(innerWidth).
		Padding(0, 1).
		Render(content)

	// Prepend title line
	title := MutedStyle.Render("Debug Log " + strings.Repeat("-", max(0, innerWidth-10)))

	return lipgloss.JoinVertical(lipgloss.Left, title, panel)
}
