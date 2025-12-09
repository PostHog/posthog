package steps

import (
	"fmt"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/installer"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type installStep int

const (
	installStepGit installStep = iota
	installStepClone
	installStepCheckout
	installStepEnv
	installStepGeoIP
	installStepScripts
	installStepCopyCompose
	installStepDockerSetup
	installStepPull
	installStepAsyncMigrations
	installStepStart
	installStepHealth
	installStepDone
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
	status installStatus
	detail string
}

type InstallModel struct {
	steps       []installItem
	currentStep installStep
	spinner     spinner.Model
	isUpgrade   bool
	version     string
	domain      string
	err         error
}

type stepResultMsg struct {
	step   installStep
	err    error
	detail string
}

func NewInstallModel() InstallModel {
	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = ui.SpinnerStyle

	return InstallModel{
		steps: []installItem{
			{name: "Setup git", status: installPending},
			{name: "Clone/update PostHog repository", status: installPending},
			{name: "Checkout version", status: installPending},
			{name: "Generate configuration", status: installPending},
			{name: "Download GeoIP database", status: installPending},
			{name: "Create startup scripts", status: installPending},
			{name: "Copy Docker Compose files", status: installPending},
			{name: "Setup Docker", status: installPending},
			{name: "Pull Docker images", status: installPending},
			{name: "Check async migrations", status: installPending},
			{name: "Start PostHog stack", status: installPending},
			{name: "Wait for PostHog to be ready", status: installPending},
		},
		currentStep: installStepGit,
		spinner:     s,
	}
}

func (m *InstallModel) SetConfig(isUpgrade bool, version, domain string) {
	m.isUpgrade = isUpgrade
	m.version = version
	m.domain = domain
}

func (m InstallModel) Init() tea.Cmd {
	return tea.Batch(
		m.spinner.Tick,
		m.runStep(installStepGit),
	)
}

func (m InstallModel) runStep(step installStep) tea.Cmd {
	return func() tea.Msg {
		var err error
		var detail string

		switch step {
		case installStepGit:
			err = installer.SetupGit()
			detail = "git ready"

		case installStepClone:
			if m.isUpgrade {
				err = installer.UpdatePostHog()
				detail = "updated"
			} else {
				err = installer.ClonePostHog()
				detail = "cloned"
			}

		case installStepCheckout:
			err = installer.CheckoutVersion(m.version)
			if err == nil {
				commit, _ := installer.GetCurrentCommit()
				detail = fmt.Sprintf("at %s", commit)
			}

		case installStepEnv:
			if m.isUpgrade {
				err = installer.UpdateEnvForUpgrade(m.version)
				detail = "updated"
			} else {
				config, configErr := installer.NewEnvConfig(m.domain, m.version)
				if configErr != nil {
					err = configErr
				} else {
					err = config.WriteEnvFile()
					detail = "created .env"
				}
			}

		case installStepGeoIP:
			if installer.GeoIPExists() {
				detail = "already exists"
			} else {
				err = installer.DownloadGeoIP()
				detail = "downloaded"
			}

		case installStepScripts:
			err = installer.CreateComposeScripts()
			detail = "created"

		case installStepCopyCompose:
			err = installer.CopyComposeFiles()
			detail = "copied"

		case installStepDockerSetup:
			if installer.IsDockerInstalled() && installer.IsDockerRunning() {
				detail = "Docker ready"
			} else if !installer.IsDockerInstalled() {
				err = installer.InstallDocker()
				if err == nil {
					err = installer.InstallDockerCompose()
				}
				detail = "installed"
			} else {
				//nolint:revive,stylecheck // ST1005: error strings should not be capitalized
				err = fmt.Errorf("docker installed but not running")
			}

		case installStepPull:
			err = installer.DockerComposePull()
			detail = "images pulled"

		case installStepAsyncMigrations:
			if m.isUpgrade {
				err = installer.RunAsyncMigrationsCheck()
				detail = "checked"
			} else {
				detail = "skipped (new install)"
			}

		case installStepStart:
			_ = installer.DockerComposeStop() // Stop any existing stack
			err = installer.DockerComposeUp()
			detail = "started"

		case installStepHealth:
			err = installer.WaitForHealth(10 * time.Minute)
			if err == nil {
				detail = "PostHog is up!"
			}
		}

		return stepResultMsg{step: step, err: err, detail: detail}
	}
}

func (m InstallModel) Update(msg tea.Msg) (InstallModel, tea.Cmd) {
	switch msg := msg.(type) {
	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	case stepResultMsg:
		idx := int(msg.step)
		if msg.err != nil {
			m.steps[idx].status = installFailed
			m.steps[idx].detail = msg.err.Error()
			m.err = msg.err
			return m, func() tea.Msg {
				return ErrorMsg{Err: msg.err}
			}
		}

		m.steps[idx].status = installSuccess
		m.steps[idx].detail = msg.detail

		// Move to next step
		nextStep := msg.step + 1
		if nextStep >= installStepDone {
			m.currentStep = installStepDone
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: nil}
			}
		}

		m.currentStep = nextStep
		m.steps[int(nextStep)].status = installRunning

		// Skip async migrations for new installs
		if nextStep == installStepAsyncMigrations && !m.isUpgrade {
			m.steps[int(nextStep)].status = installSkipped
			m.steps[int(nextStep)].detail = "new install"
			nextStep++
			if nextStep < installStepDone {
				m.currentStep = nextStep
				m.steps[int(nextStep)].status = installRunning
			}
		}

		return m, m.runStep(nextStep)
	}

	return m, nil
}

func (m InstallModel) View() string {
	var lines []string

	for i, step := range m.steps {
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

		// Set first step as running if it's pending
		if i == 0 && step.status == installPending && m.currentStep == 0 {
			m.steps[0].status = installRunning
		}

		lines = append(lines, line)
	}

	title := "Installing PostHog"
	if m.isUpgrade {
		title = "Upgrading PostHog"
	}

	var footer string
	if m.currentStep == installStepDone {
		footer = "\n" + ui.SuccessStyle.Render("✓ Installation complete!")
	} else if m.err != nil {
		footer = "\n" + ui.ErrorStyle.Render("✗ Installation failed: "+m.err.Error())
	}

	content := lipgloss.JoinVertical(
		lipgloss.Left,
		ui.TitleStyle.Render(title),
		"",
		ui.SubtitleStyle.Render(fmt.Sprintf("Version: %s | Domain: %s", m.version, m.domain)),
		"",
		lipgloss.JoinVertical(lipgloss.Left, lines...),
		footer,
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}
