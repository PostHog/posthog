package main

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/steps"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type model struct {
	checks steps.ChecksModel
	width  int
	height int
	done   bool
}

func initialModel() model {
	return model{
		checks: steps.NewChecksModel(),
	}
}

func (m model) Init() tea.Cmd {
	return m.checks.Init()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q", "esc":
			return m, tea.Quit
		case "r":
			// Restart checks
			m.checks = steps.NewChecksModel()
			m.done = false
			return m, m.checks.Init()
		}
	case steps.StepCompleteMsg:
		m.done = true
		return m, nil
	case steps.ErrorMsg:
		m.done = true
		return m, nil
	}

	var cmd tea.Cmd
	m.checks, cmd = m.checks.Update(msg)
	return m, cmd
}

func (m model) View() string {
	content := m.checks.View()

	// Add demo controls
	controls := ui.HelpStyle.Render("\n\nr restart checks • q/esc quit")
	content = lipgloss.JoinVertical(lipgloss.Left, content, controls)

	if m.width > 0 && m.height > 0 {
		return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, content)
	}
	return content
}

func main() {
	p := tea.NewProgram(initialModel(), tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
