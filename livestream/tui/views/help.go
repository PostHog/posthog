package views

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

type HelpView struct {
	visible bool
	width   int
	height  int
}

func NewHelpView() *HelpView {
	return &HelpView{}
}

func (v *HelpView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

func (v *HelpView) Toggle() {
	v.visible = !v.visible
}

func (v *HelpView) IsVisible() bool {
	return v.visible
}

func (v *HelpView) Close() {
	v.visible = false
}

func (v *HelpView) View() string {
	if !v.visible {
		return ""
	}

	borderStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"}).
		Padding(1, 2).
		Width(v.width - 8).
		Height(v.height - 4)

	titleStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"})

	keyStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"}).
		Bold(true).
		Width(14)

	descStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#1D1F27", Dark: "#EDEDEC"})

	bindings := []struct{ key, desc string }{
		{"q / Ctrl+C", "Quit"},
		{"p", "Pause/resume event stream"},
		{"f", "Set event type filter"},
		{"d", "Set distinct ID filter"},
		{"c", "Set property columns (name:width)"},
		{"Enter", "Open event detail view"},
		{"Esc", "Close detail/filter/help"},
		{"?", "Toggle this help"},
		{"x", "Clear events"},
		{"j / Down", "Move cursor down"},
		{"k / Up", "Move cursor up"},
	}

	var lines []string
	lines = append(lines, titleStyle.Render("Keyboard Shortcuts"))
	lines = append(lines, "")
	for _, b := range bindings {
		lines = append(lines, keyStyle.Render(b.key)+descStyle.Render(b.desc))
	}

	return lipgloss.Place(v.width, v.height,
		lipgloss.Center, lipgloss.Center,
		borderStyle.Render(strings.Join(lines, "\n")),
	)
}
