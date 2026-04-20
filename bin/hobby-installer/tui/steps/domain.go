package steps

import (
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/core"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type DomainModel struct {
	textInput textinput.Model
}

func NewDomainModel() DomainModel {
	ti := textinput.New()
	ti.Placeholder = "e.g., posthog.example.com"
	ti.CharLimit = 256
	ti.Width = 50
	ti.Focus()

	return DomainModel{
		textInput: ti,
	}
}

func (m DomainModel) Init() tea.Cmd {
	return textinput.Blink
}

func (m DomainModel) Update(msg tea.Msg) (DomainModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "enter":
			domain := strings.TrimSpace(m.textInput.Value())
			if domain != "" && isValidDomain(domain) {
				return m, func() tea.Msg {
					return StepCompleteMsg{Data: domain}
				}
			}
		}
	}

	var cmd tea.Cmd
	m.textInput, cmd = m.textInput.Update(msg)
	return m, cmd
}

func (m DomainModel) View() string {
	content := lipgloss.JoinVertical(
		lipgloss.Left,
		ui.TitleStyle.Render("Configure Domain"),
		"",
		ui.SubtitleStyle.Render("Enter the domain where PostHog will be accessible:"),
		"",
		m.textInput.View(),
		"",
		ui.WarningStyle.Render("⚠️  Important:"),
		ui.MutedStyle.Render("• Make sure you have a DNS A record pointing to this server"),
		ui.MutedStyle.Render("• This will be used for TLS certificate generation"),
		ui.MutedStyle.Render("• Do NOT enter an IP address"),
		"",
		ui.HelpStyle.Render("enter confirm • esc back"),
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}

// GetExistingDomain checks if a domain already exists in .env file
func (m DomainModel) GetExistingDomain() string {
	return core.GetExistingDomain()
}

func isValidDomain(domain string) bool {
	// Basic validation: not empty, no spaces, contains at least one dot
	if domain == "" || strings.Contains(domain, " ") {
		return false
	}

	// Should not be an IP address (simple check)
	parts := strings.Split(domain, ".")
	return len(parts) >= 2
}
