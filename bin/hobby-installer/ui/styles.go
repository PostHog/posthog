package ui

import "github.com/charmbracelet/lipgloss"

var (
	// Colors - PostHog brand colors
	ColorPrimary   = lipgloss.Color("#F54E00") // PostHog orange
	ColorSecondary = lipgloss.Color("#1D4AFF") // PostHog blue
	ColorSuccess   = lipgloss.Color("#77B96C") // Green
	ColorWarning   = lipgloss.Color("#F1A82C") // Yellow/orange
	ColorError     = lipgloss.Color("#F54E00") // Red/orange
	ColorMuted     = lipgloss.Color("#6B7280") // Gray
	ColorWhite     = lipgloss.Color("#FFFFFF")
	ColorBlack     = lipgloss.Color("#000000")

	// Adaptive color that works on both light and dark backgrounds
	ColorText = lipgloss.AdaptiveColor{Light: "#1A1A1A", Dark: "#FFFFFF"}

	// Base styles
	TitleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(ColorPrimary).
			MarginBottom(1)

	SubtitleStyle = lipgloss.NewStyle().
			Foreground(ColorMuted).
			MarginBottom(1)

	// Box/container styles
	BoxStyle = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(ColorPrimary).
			Padding(1, 2)

	// Text styles
	DefaultStyle = lipgloss.NewStyle().Foreground(ColorText)

	BoldStyle = lipgloss.NewStyle().Bold(true)

	MutedStyle = lipgloss.NewStyle().Foreground(ColorMuted)

	SuccessStyle = lipgloss.NewStyle().Foreground(ColorSuccess)

	ErrorStyle = lipgloss.NewStyle().Foreground(ColorError)

	WarningStyle = lipgloss.NewStyle().Foreground(ColorWarning)

	// Interactive elements
	SelectedStyle = lipgloss.NewStyle().
			Foreground(ColorPrimary).
			Bold(true)

	UnselectedStyle = lipgloss.NewStyle().
			Foreground(ColorMuted)

	// Input styles
	InputPromptStyle = lipgloss.NewStyle().
				Foreground(ColorPrimary).
				Bold(true)

	InputTextStyle = lipgloss.NewStyle().
			Foreground(ColorText)

	// Progress/status styles
	SpinnerStyle = lipgloss.NewStyle().Foreground(ColorPrimary)

	CheckmarkStyle = lipgloss.NewStyle().
			Foreground(ColorSuccess).
			SetString("✓")

	CrossStyle = lipgloss.NewStyle().
			Foreground(ColorError).
			SetString("✗")

	// Layout helpers
	CenterStyle = lipgloss.NewStyle().
			Align(lipgloss.Center)

	// Help text
	HelpStyle = lipgloss.NewStyle().
			Foreground(ColorMuted).
			MarginTop(1)
)

// Checkmark returns a styled checkmark
func Checkmark() string {
	return SuccessStyle.Render("✓")
}

// Cross returns a styled cross/X
func Cross() string {
	return ErrorStyle.Render("✗")
}

// Spinner returns a styled spinner character
func Spinner() string {
	return SpinnerStyle.Render("◐")
}
