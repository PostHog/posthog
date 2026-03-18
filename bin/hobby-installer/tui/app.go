package tui

import (
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/tui/steps"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type step int

const (
	stepWelcome step = iota
	stepVersion
	stepDomain
	stepChecks
	stepInstall
	stepComplete
)

type mode int

const (
	modeInstall mode = iota
	modeUpgrade
)

type model struct {
	step     step
	mode     mode
	quitting bool
	err      error
	width    int
	height   int

	welcome  steps.WelcomeModel
	version  steps.VersionModel
	domain   steps.DomainModel
	checks   steps.ChecksModel
	install  steps.InstallModel
	complete steps.CompleteModel

	posthogVersion string
	posthogDomain  string
}

func initialModel() model {
	return model{
		step:    stepWelcome,
		welcome: steps.NewWelcomeModel(),
		version: steps.NewVersionModel(),
		domain:  steps.NewDomainModel(),
		checks:  steps.NewChecksModel(),
		install: steps.NewInstallModel(),
	}
}

func (m model) Init() tea.Cmd {
	return m.welcome.Init()
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c":
			m.quitting = true
			return m, tea.Quit
		case "esc":
			if m.step == stepVersion && m.version.IsCustomMode() {
				break
			}
			return m.goBack()
		}
	case steps.StepCompleteMsg:
		return m.advanceStep(msg)
	case steps.ErrorMsg:
		m.err = msg.Err
		m.complete = steps.NewCompleteModel(false, msg.Err.Error(), m.posthogDomain)
		m.step = stepComplete
		return m, m.complete.Init()
	}

	var cmd tea.Cmd
	switch m.step {
	case stepWelcome:
		m.welcome, cmd = m.welcome.Update(msg)
	case stepVersion:
		m.version, cmd = m.version.Update(msg)
	case stepDomain:
		m.domain, cmd = m.domain.Update(msg)
	case stepChecks:
		m.checks, cmd = m.checks.Update(msg)
	case stepInstall:
		m.install, cmd = m.install.Update(msg)
	case stepComplete:
		m.complete, cmd = m.complete.Update(msg)
	}
	return m, cmd
}

func (m model) goBack() (tea.Model, tea.Cmd) {
	switch m.step {
	case stepWelcome:
		m.quitting = true
		return m, tea.Quit
	case stepVersion:
		m.step = stepWelcome
		m.welcome = steps.NewWelcomeModel()
		return m, m.welcome.Init()
	case stepDomain:
		m.step = stepVersion
		m.version = steps.NewVersionModel()
		return m, m.version.Init()
	case stepChecks:
		m.step = stepDomain
		m.domain = steps.NewDomainModel()
		return m, m.domain.Init()
	case stepInstall, stepComplete:
		return m, nil
	}
	return m, nil
}

func (m model) advanceStep(msg steps.StepCompleteMsg) (tea.Model, tea.Cmd) {
	switch m.step {
	case stepWelcome:
		m.mode = mode(msg.Data.(int))
		m.step = stepVersion
		m.version = steps.NewVersionModel()
		return m, m.version.Init()

	case stepVersion:
		m.posthogVersion = msg.Data.(string)
		if existingDomain := m.domain.GetExistingDomain(); existingDomain != "" {
			m.posthogDomain = existingDomain
			m.step = stepChecks
			m.checks = steps.NewChecksModel()
			return m, m.checks.Init()
		}
		m.step = stepDomain
		m.domain = steps.NewDomainModel()
		return m, m.domain.Init()

	case stepDomain:
		m.posthogDomain = msg.Data.(string)
		m.step = stepChecks
		m.checks = steps.NewChecksModel()
		return m, m.checks.Init()

	case stepChecks:
		m.step = stepInstall
		m.install = steps.NewInstallModel()
		m.install.SetConfig(m.mode == modeUpgrade, m.posthogVersion, m.posthogDomain)
		return m, m.install.Init()

	case stepInstall:
		m.step = stepComplete
		m.complete = steps.NewCompleteModel(true, "", m.posthogDomain)
		return m, m.complete.Init()
	}
	return m, nil
}

func (m model) View() string {
	var content string

	if m.quitting {
		content = ui.GoodbyeView()
	} else {
		switch m.step {
		case stepWelcome:
			content = m.welcome.View()
		case stepVersion:
			content = m.version.View()
		case stepDomain:
			content = m.domain.View()
		case stepChecks:
			content = m.checks.View()
		case stepInstall:
			content = m.install.View()
		case stepComplete:
			content = m.complete.View()
		}
	}

	if m.width > 0 && m.height > 0 {
		return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, content)
	}
	return content
}

func Run() error {
	p := tea.NewProgram(initialModel(), tea.WithAltScreen())

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return err
	}

	return nil
}
