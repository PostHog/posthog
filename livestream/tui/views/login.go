package views

import (
	"fmt"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/lipgloss"
)

type LoginView struct {
	spinner spinner.Model
	url     string
	width   int
	height  int
}

func NewLoginView() *LoginView {
	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"})
	return &LoginView{spinner: s}
}

func (v *LoginView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

func (v *LoginView) SetURL(url string) {
	v.url = url
}

func (v *LoginView) Spinner() spinner.Model {
	return v.spinner
}

func (v *LoginView) UpdateSpinner(msg spinner.TickMsg) spinner.Model {
	var cmd interface{}
	_ = cmd
	v.spinner, _ = v.spinner.Update(msg)
	return v.spinner
}

func (v *LoginView) View() string {
	titleStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"})

	urlStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#1D4AFF", Dark: "#1D4AFF"}).
		Underline(true)

	mutedStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})

	content := fmt.Sprintf(
		"\n\n%s\n\n%s Open your browser to authorize...\n\n%s\n\n%s\n",
		titleStyle.Render("PostHog Live"),
		v.spinner.View(),
		urlStyle.Render(v.url),
		mutedStyle.Render("Waiting for authorization from browser..."),
	)

	return lipgloss.Place(v.width, v.height,
		lipgloss.Center, lipgloss.Center,
		content,
	)
}
