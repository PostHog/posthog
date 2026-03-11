package tui

import "charm.land/lipgloss/v2"

// Plain Unicode, no embedded ANSI so they can be safely composed
// without resetting the enclosing background or foreground colour
const (
	iconCharRunning = "●"
	iconCharPending = "◌"
	iconCharStopped = "○"
	iconCharDone    = "✓"
	iconCharCrashed = "✗"
)

var (
	colorYellow   = lipgloss.Color("#F7A501")
	colorBlue     = lipgloss.Color("#1D4AFF")
	colorGrey     = lipgloss.Color("#9BA1B2")
	colorDarkGrey = lipgloss.Color("#3D3F43")
	colorGreen    = lipgloss.Color("#2DCC5D")
	colorRed      = lipgloss.Color("#F04438")
	colorWhite    = lipgloss.Color("#FFFFFF")
	colorBlack    = lipgloss.Color("#151515")
)

// Outer width of the process list column (including border)
const sidebarWidth = 24

const headerHeight = 1
const footerHeightShort = 3
const footerHeightFull = 5

var (
	// Header
	headerBrandStyle = lipgloss.NewStyle().
				Foreground(colorWhite).
				Bold(true).
				Padding(0, 1)

	headerMetaStyle = lipgloss.NewStyle().
			Foreground(colorGrey).
			Padding(0, 1)

	// Sidebar
	sidebarBorderStyle = lipgloss.NewStyle().
				BorderRight(true).
				BorderTop(true).
				BorderBottom(true).
				BorderLeft(true).
				BorderStyle(lipgloss.NormalBorder()).
				BorderForeground(colorDarkGrey)

	procInactiveStyle = lipgloss.NewStyle().
				PaddingLeft(1).
				Foreground(colorGrey)

	// Output
	outputBorderStyle = lipgloss.NewStyle().
				BorderRight(true).
				BorderTop(true).
				BorderBottom(true).
				BorderLeft(true).
				BorderStyle(lipgloss.NormalBorder()).
				BorderForeground(colorDarkGrey)

	// Footer
	footerStyle = lipgloss.NewStyle().
			Foreground(colorGrey).
			PaddingLeft(1)
)
