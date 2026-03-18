package ui

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// ProgressItem represents a single progress item with status
type ProgressItem struct {
	Label  string
	Status ProgressStatus
	Detail string
}

type ProgressStatus int

const (
	StatusPending ProgressStatus = iota
	StatusRunning
	StatusSuccess
	StatusFailed
	StatusSkipped
)

// RenderProgressItem renders a single progress item with appropriate styling
func RenderProgressItem(item ProgressItem, spinnerFrame string) string {
	var icon string
	var style lipgloss.Style

	switch item.Status {
	case StatusPending:
		icon = "○"
		style = MutedStyle
	case StatusRunning:
		icon = spinnerFrame
		style = lipgloss.NewStyle().Foreground(ColorPrimary)
	case StatusSuccess:
		icon = "✓"
		style = SuccessStyle
	case StatusFailed:
		icon = "✗"
		style = ErrorStyle
	case StatusSkipped:
		icon = "◌"
		style = MutedStyle
	}

	result := fmt.Sprintf("%s %s", style.Render(icon), style.Render(item.Label))
	if item.Detail != "" {
		result += MutedStyle.Render(fmt.Sprintf(" (%s)", item.Detail))
	}
	return result
}

// RenderProgressList renders a list of progress items
func RenderProgressList(items []ProgressItem, spinnerFrame string) string {
	var lines []string
	for _, item := range items {
		lines = append(lines, RenderProgressItem(item, spinnerFrame))
	}
	return strings.Join(lines, "\n")
}

// RenderMenuItems renders a menu with selection indicator
func RenderMenuItems(items []string, selected int) string {
	var lines []string
	for i, item := range items {
		if i == selected {
			lines = append(lines, SelectedStyle.Render(fmt.Sprintf("› %s", item)))
		} else {
			lines = append(lines, UnselectedStyle.Render(fmt.Sprintf("  %s", item)))
		}
	}
	return strings.Join(lines, "\n")
}

// RenderKeyHelp renders help text for available keys
func RenderKeyHelp(keys map[string]string) string {
	var parts []string
	for key, action := range keys {
		parts = append(parts, fmt.Sprintf("%s %s", BoldStyle.Render(key), MutedStyle.Render(action)))
	}
	return HelpStyle.Render(strings.Join(parts, "  •  "))
}

// RenderBox wraps content in a styled box
func RenderBox(content string, title string) string {
	box := BoxStyle.Render(content)
	if title != "" {
		titleRendered := TitleStyle.Render(title)
		return lipgloss.JoinVertical(lipgloss.Left, titleRendered, box)
	}
	return box
}

// RenderCentered centers content horizontally
func RenderCentered(content string, width int) string {
	return lipgloss.NewStyle().Width(width).Align(lipgloss.Center).Render(content)
}

// RenderWarningBox renders a warning message in a styled box
func RenderWarningBox(message string) string {
	style := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(ColorWarning).
		Foreground(ColorWarning).
		Padding(1, 2)
	return style.Render("⚠️  " + message)
}

// RenderErrorBox renders an error message in a styled box
func RenderErrorBox(message string) string {
	style := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(ColorError).
		Foreground(ColorError).
		Padding(1, 2)
	return style.Render("✗ " + message)
}

// RenderSuccessBox renders a success message in a styled box
func RenderSuccessBox(message string) string {
	style := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(ColorSuccess).
		Foreground(ColorSuccess).
		Padding(1, 2)
	return style.Render("✓ " + message)
}

// RenderInfoBox renders an info message in a styled box
func RenderInfoBox(message string) string {
	style := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(ColorSecondary).
		Foreground(ColorText).
		Padding(1, 2)
	return style.Render("ℹ " + message)
}

// Divider returns a horizontal divider line
func Divider(width int) string {
	return MutedStyle.Render(strings.Repeat("─", width))
}
