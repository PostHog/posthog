package steps

import (
	"fmt"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type CompleteModel struct {
	success bool
	error   string
	domain  string
}

func NewCompleteModel(success bool, errorMsg, domain string) CompleteModel {
	return CompleteModel{
		success: success,
		error:   errorMsg,
		domain:  domain,
	}
}

func (m CompleteModel) Init() tea.Cmd {
	return nil
}

func (m CompleteModel) Update(msg tea.Msg) (CompleteModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "enter", "q", "ctrl+c":
			return m, tea.Quit
		}
	}
	return m, nil
}

func (m CompleteModel) View() string {
	if m.success {
		return m.successView()
	}
	return m.errorView()
}

func (m CompleteModel) successView() string {
	successBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(ui.ColorSuccess).
		Padding(1, 3).
		Render(lipgloss.JoinVertical(
			lipgloss.Center,
			ui.SuccessStyle.Render("🎉 Installation Complete! 🎉"),
			"",
			ui.DefaultStyle.Render("PostHog is now running at:"),
			"",
			ui.BoldStyle.Foreground(ui.ColorPrimary).Render(fmt.Sprintf("https://%s", m.domain)),
		))

	tips := lipgloss.JoinVertical(
		lipgloss.Left,
		ui.SubtitleStyle.Render("Useful commands:"),
		"",
		ui.MutedStyle.Render("  Stop PostHog:    ")+"docker-compose stop",
		ui.MutedStyle.Render("  Start PostHog:   ")+"docker-compose start",
		ui.MutedStyle.Render("  View logs:       ")+"docker-compose logs -f",
		ui.MutedStyle.Render("  Upgrade:         ")+"./posthog-hobby",
		"",
		ui.MutedStyle.Render("  Clean up old images: ")+"docker system prune -a",
	)

	content := lipgloss.JoinVertical(
		lipgloss.Center,
		"",
		successBox,
		"",
		tips,
		"",
		ui.MutedStyle.Render("It's dangerous to go alone! Take this: 🦔"),
		"",
		ui.HelpStyle.Render("Press enter or q to exit"),
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}

func (m CompleteModel) errorView() string {
	errorBox := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(ui.ColorError).
		Padding(1, 3).
		Render(lipgloss.JoinVertical(
			lipgloss.Center,
			ui.ErrorStyle.Render("✗ Installation Failed"),
			"",
			ui.MutedStyle.Render("Error:"),
			m.error,
		))

	tips := lipgloss.JoinVertical(
		lipgloss.Left,
		ui.SubtitleStyle.Render("Troubleshooting:"),
		"",
		ui.MutedStyle.Render("  • Check Docker is running: ")+"docker info",
		ui.MutedStyle.Render("  • View logs: ")+"docker-compose logs",
		ui.MutedStyle.Render("  • Check disk space: ")+"df -h",
		ui.MutedStyle.Render("  • Check memory: ")+"free -h",
		"",
		ui.MutedStyle.Render("  • Delete everything and try again:"),
		"    rm -rf posthog docker-compose.yml .env",
		"    ./posthog-hobby",
	)

	content := lipgloss.JoinVertical(
		lipgloss.Center,
		"",
		errorBox,
		"",
		tips,
		"",
		ui.HelpStyle.Render("Press enter or q to exit"),
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}
