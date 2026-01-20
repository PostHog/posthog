package main

import (
	"flag"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/core"
	"github.com/posthog/posthog/bin/hobby-installer/tui/steps"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

func main() {
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s <demo>\n\n", os.Args[0])
		fmt.Fprintln(os.Stderr, "Available demos:")
		fmt.Fprintln(os.Stderr, "  checks    Run the system checks demo")
		fmt.Fprintln(os.Stderr, "")
	}
	flag.Parse()

	if flag.NArg() < 1 {
		flag.Usage()
		os.Exit(1)
	}

	demo := flag.Arg(0)
	var err error

	switch demo {
	case "checks":
		err = runChecksDemo()
	default:
		fmt.Fprintf(os.Stderr, "Unknown demo: %s\n\n", demo)
		flag.Usage()
		os.Exit(1)
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

// Checks demo
type checksModel struct {
	checks steps.ChecksModel
	width  int
	height int
	done   bool
}

func runChecksDemo() error {
	logger := core.GetLogger()
	logger.WriteString("PostHog Hobby Installer - Checks Demo\n")
	logger.WriteString("Starting system checks...\n")

	m := checksModel{checks: steps.NewChecksModel()}
	p := tea.NewProgram(m, tea.WithAltScreen())
	_, err := p.Run()
	return err
}

func (m checksModel) Init() tea.Cmd {
	return m.checks.Init()
}

func (m checksModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "q", "esc":
			return m, tea.Quit
		case "r":
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

func (m checksModel) View() string {
	content := m.checks.View()
	controls := ui.HelpStyle.Render("\n\nr restart • q/esc quit")
	content = lipgloss.JoinVertical(lipgloss.Left, content, controls)

	if m.width > 0 && m.height > 0 {
		return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, content)
	}
	return content
}
