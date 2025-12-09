package steps

import (
	"github.com/charmbracelet/bubbles/key"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type WelcomeModel struct {
	selected int
	options  []string
}

func NewWelcomeModel() WelcomeModel {
	return WelcomeModel{
		selected: 0,
		options:  []string{"Install PostHog", "Upgrade PostHog"},
	}
}

func (m WelcomeModel) Init() tea.Cmd {
	return nil
}

func (m WelcomeModel) Update(msg tea.Msg) (WelcomeModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch {
		case key.Matches(msg, key.NewBinding(key.WithKeys("up", "k"))):
			if m.selected > 0 {
				m.selected--
			}
		case key.Matches(msg, key.NewBinding(key.WithKeys("down", "j"))):
			if m.selected < len(m.options)-1 {
				m.selected++
			}
		case key.Matches(msg, key.NewBinding(key.WithKeys("enter"))):
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: m.selected}
			}
		}
	}
	return m, nil
}

func (m WelcomeModel) View() string {
	// Build the welcome screen
	content := lipgloss.JoinVertical(
		lipgloss.Center,
		ui.GetWelcomeArt(),
		"",
		ui.TitleStyle.Render("Welcome to the PostHog Self-Hosted Installer"),
		"",
		ui.SubtitleStyle.Render("What would you like to do?"),
		"",
		ui.RenderMenuItems(m.options, m.selected),
		"",
		"",
		ui.HelpStyle.Render("↑/↓ navigate • enter select • esc quit"),
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}

