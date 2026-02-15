package steps

import (
	"fmt"

	"github.com/charmbracelet/bubbles/spinner"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/core"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type installStatus int

const (
	installPending installStatus = iota
	installRunning
	installSuccess
	installFailed
	installSkipped
)

type installItem struct {
	name   string
	hidden bool
	status installStatus
	detail string
}

type InstallModel struct {
	steps       []installItem
	coreSteps   []core.InstallStep
	currentStep int
	spinner     spinner.Model
	config      core.InstallConfig
	err         error
	width       int
	height      int
}

type stepResultMsg struct {
	stepIdx int
	err     error
	detail  string
	skipped bool
}

func NewInstallModel() InstallModel {
	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = ui.SpinnerStyle

	coreSteps := core.GetInstallSteps()
	steps := make([]installItem, len(coreSteps))
	for i, step := range coreSteps {
		steps[i] = installItem{name: step.Name, status: installPending, hidden: step.Hidden}
	}

	return InstallModel{
		steps:       steps,
		coreSteps:   coreSteps,
		currentStep: 0,
		spinner:     s,
	}
}

func (m *InstallModel) SetConfig(isUpgrade bool, version, domain string) {
	m.config = core.InstallConfig{
		IsUpgrade: isUpgrade,
		Version:   version,
		Domain:    domain,
	}
}

func (m InstallModel) Init() tea.Cmd {
	return tea.Batch(
		m.spinner.Tick,
		m.runStep(0),
	)
}

func (m InstallModel) runStep(index int) tea.Cmd {
	return func() tea.Msg {
		if index >= len(m.coreSteps) {
			return nil
		}

		step := m.coreSteps[index]

		if step.Skip != nil {
			if skip, reason := step.Skip(m.config); skip {
				return stepResultMsg{stepIdx: index, skipped: true, detail: reason}
			}
		}

		result := step.Run(m.config)
		return stepResultMsg{stepIdx: index, err: result.Err, detail: result.Detail}
	}
}

func (m InstallModel) Update(msg tea.Msg) (InstallModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	case stepResultMsg:
		if msg.skipped {
			m.steps[msg.stepIdx].status = installSkipped
			m.steps[msg.stepIdx].detail = msg.detail
		} else if msg.err != nil {
			m.steps[msg.stepIdx].status = installFailed
			m.steps[msg.stepIdx].detail = msg.err.Error()
			m.err = msg.err
			return m, func() tea.Msg {
				return ErrorMsg{Err: msg.err}
			}
		} else {
			m.steps[msg.stepIdx].status = installSuccess
			m.steps[msg.stepIdx].detail = msg.detail
		}

		nextStep := msg.stepIdx + 1
		if nextStep >= len(m.coreSteps) {
			m.currentStep = len(m.coreSteps)
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: nil}
			}
		}

		m.currentStep = nextStep
		m.steps[nextStep].status = installRunning
		return m, m.runStep(nextStep)
	}

	return m, nil
}

func (m InstallModel) View() string {
	var lines []string

	for i, step := range m.steps {
		if step.hidden {
			continue
		}

		var icon string
		var style lipgloss.Style

		switch step.status {
		case installPending:
			icon = "○"
			style = ui.MutedStyle
		case installRunning:
			icon = m.spinner.View()
			style = lipgloss.NewStyle().Foreground(ui.ColorPrimary)
		case installSuccess:
			icon = ui.Checkmark()
			style = ui.SuccessStyle
		case installFailed:
			icon = ui.Cross()
			style = ui.ErrorStyle
		case installSkipped:
			icon = "◌"
			style = ui.MutedStyle
		}

		line := fmt.Sprintf("  %s %s", icon, style.Render(step.name))
		if step.detail != "" && step.status != installPending && step.status != installRunning {
			line += ui.MutedStyle.Render(fmt.Sprintf(" (%s)", step.detail))
		}

		if i == 0 && step.status == installPending && m.currentStep == 0 {
			m.steps[0].status = installRunning
		}

		lines = append(lines, line)
	}

	title := "Setting up PostHog"

	var footer string
	if m.currentStep >= len(m.coreSteps) {
		footer = "\n" + ui.SuccessStyle.Render("✓ Installation complete!")
	} else if m.err != nil {
		footer = "\n" + ui.ErrorStyle.Render("✗ Installation failed: "+m.err.Error())
	}

	logLines := core.GetLogger().GetLines(5)
	logPanel := ui.RenderLogPanel(logLines, 100, 7)

	content := lipgloss.JoinVertical(
		lipgloss.Left,
		ui.TitleStyle.Render(title),
		"",
		ui.SubtitleStyle.Render(fmt.Sprintf("Version: %s | Domain: %s", m.config.Version, m.config.Domain)),
		"",
		lipgloss.JoinVertical(lipgloss.Left, lines...),
		footer,
		"",
		logPanel,
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}
