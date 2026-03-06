package tui

import "github.com/charmbracelet/lipgloss"

// Process status icon runes — plain Unicode, no embedded ANSI so they can be
// safely composed inside a larger lipgloss-styled container without resetting
// the enclosing background or foreground colour.
const (
	iconCharRunning = "●"
	iconCharPending = "◌"
	iconCharStopped = "○"
	iconCharDone    = "✓"
	iconCharCrashed = "✗"
)

// PostHog brand palette.
const (
	colorOrange   = lipgloss.Color("#F54E00")
	colorBlue     = lipgloss.Color("#1D4AFF")
	colorGrey     = lipgloss.Color("#9BA1B2")
	colorDarkGrey = lipgloss.Color("#3D3F43")
	colorGreen    = lipgloss.Color("#2DCC5D")
	colorRed      = lipgloss.Color("#F04438")
	colorYellow   = lipgloss.Color("#F9A825")
	colorWhite    = lipgloss.Color("#FFFFFF")
)

// sidebarWidth is the outer width of the process list column (including border).
const sidebarWidth = 24

var (
	// Header
	headerBrandStyle = lipgloss.NewStyle().
				Background(colorOrange).
				Foreground(colorWhite).
				Bold(true).
				Padding(0, 1)

	headerMetaStyle = lipgloss.NewStyle().
			Background(colorOrange).
			Foreground(lipgloss.Color("#FFD0BD")).
			Padding(0, 1)

	// Sidebar
	sidebarBorderStyle = lipgloss.NewStyle().
				BorderRight(true).
				BorderStyle(lipgloss.NormalBorder()).
				BorderForeground(colorDarkGrey)

	sidebarTitleStyle = lipgloss.NewStyle().
				Foreground(colorGrey).
				Bold(true).
				PaddingLeft(1).
				PaddingBottom(1)

	procActiveStyle = lipgloss.NewStyle().
			PaddingLeft(1).
			Background(colorDarkGrey).
			Foreground(colorWhite).
			Bold(true)

	procInactiveStyle = lipgloss.NewStyle().
				PaddingLeft(1).
				Foreground(colorGrey)

	// Footer
	footerStyle = lipgloss.NewStyle().
			BorderTop(true).
			BorderStyle(lipgloss.NormalBorder()).
			BorderForeground(colorDarkGrey).
			Foreground(colorGrey).
			PaddingLeft(1)
)
