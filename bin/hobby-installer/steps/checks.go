package steps

import (
	"fmt"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/installer"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type checkStatus int

const (
	checkPending checkStatus = iota
	checkRunning
	checkPassed
	checkFailed
	checkWarning
)

type systemCheck struct {
	name   string
	status checkStatus
	detail string
}

type ChecksModel struct {
	checks      []systemCheck
	current     int
	spinner     spinner.Model
	done        bool
	allGood     bool
	hasWarnings bool
	confirmed   bool
	width       int
	height      int
}

type checkResultMsg struct {
	index   int
	passed  bool
	warning bool
	detail  string
}

type allChecksCompleteMsg struct{}

func NewChecksModel() ChecksModel {
	s := spinner.New()
	s.Spinner = spinner.Dot
	s.Style = ui.SpinnerStyle

	return ChecksModel{
		checks: []systemCheck{
			{name: "Docker installed", status: checkPending},
			{name: "Docker Compose available", status: checkPending},
			{name: "Memory (8GB+ recommended)", status: checkPending},
			{name: "Disk space available", status: checkPending},
			{name: "Network connectivity", status: checkPending},
			{name: "Docker volumes", status: checkPending},
		},
		current: 0,
		spinner: s,
		done:    false,
		allGood: true,
	}
}

func (m ChecksModel) Init() tea.Cmd {
	return tea.Batch(
		m.spinner.Tick,
		m.runCheck(0),
	)
}

func (m ChecksModel) runCheck(index int) tea.Cmd {
	return func() tea.Msg {
		time.Sleep(300 * time.Millisecond) // Small delay for visual effect

		switch index {
		case 0:
			return m.checkDocker()
		case 1:
			return m.checkDockerCompose()
		case 2:
			return m.checkMemory()
		case 3:
			return m.checkDiskSpace()
		case 4:
			return m.checkNetwork()
		case 5:
			return m.checkDockerVolumes()
		}
		return nil
	}
}

func (m ChecksModel) checkDocker() checkResultMsg {
	logger := installer.GetLogger()
	logger.WriteString("Checking for Docker...\n")

	_, err := exec.LookPath("docker")
	if err != nil {
		logger.WriteString("✗ Docker not found in PATH\n")
		return checkResultMsg{index: 0, passed: false, detail: "Docker not found in PATH"}
	}

	logger.WriteString("$ docker info\n")
	cmd := exec.Command("docker", "info")
	if err := cmd.Run(); err != nil {
		logger.WriteString("✗ Docker daemon not running\n")
		return checkResultMsg{index: 0, passed: false, detail: "Docker daemon not running"}
	}

	logger.WriteString("✓ Docker is running\n")
	return checkResultMsg{index: 0, passed: true, detail: "Docker is running"}
}

func (m ChecksModel) checkDockerCompose() checkResultMsg {
	logger := installer.GetLogger()
	logger.WriteString("Checking for Docker Compose...\n")

	// Check for docker-compose or docker compose
	_, err := exec.LookPath("docker-compose")
	if err == nil {
		logger.WriteString("✓ docker-compose available\n")
		return checkResultMsg{index: 1, passed: true, detail: "docker-compose available"}
	}

	logger.WriteString("$ docker compose version\n")
	cmd := exec.Command("docker", "compose", "version")
	if err := cmd.Run(); err == nil {
		logger.WriteString("✓ docker compose available\n")
		return checkResultMsg{index: 1, passed: true, detail: "docker compose available"}
	}

	logger.WriteString("✗ Docker Compose not found\n")
	return checkResultMsg{index: 1, passed: false, detail: "Docker Compose not found"}
}

func (m ChecksModel) checkMemory() checkResultMsg {
	logger := installer.GetLogger()
	logger.WriteString("Checking system memory...\n")

	// Try to get memory info (Linux-specific, will be run on Ubuntu)
	scale := int64(1024 * 1024) // Linux command will return KiB
	cmd := exec.Command("sh", "-c", "grep MemTotal /proc/meminfo | awk '{print $2}'")
	out, err := cmd.Output()

	if err != nil || string(out) == "" {
		// On macOS during development, use sysctl
		scale = int64(1024 * 1024 * 1024) // macOS command will return bytes (B)
		logger.WriteString("$ sysctl -n hw.memsize\n")
		cmd = exec.Command("sysctl", "-n", "hw.memsize")
		out, err = cmd.Output()

		if err != nil || string(out) == "" {
			logger.WriteString("⚠ Could not check memory\n")
			return checkResultMsg{index: 2, passed: true, warning: true, detail: "Could not check memory"}
		}
	}

	memKB, _ := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
	memGB := memKB / scale
	logger.WriteString(fmt.Sprintf("Memory: %dGB\n", memGB))

	if memGB < 8 {
		return checkResultMsg{index: 2, passed: true, warning: true, detail: fmt.Sprintf("%dGB (8GB+ recommended)", memGB)}
	}
	return checkResultMsg{index: 2, passed: true, detail: fmt.Sprintf("%dGB available", memGB)}
}

func (m ChecksModel) checkDiskSpace() checkResultMsg {
	logger := installer.GetLogger()
	logger.WriteString("$ df -h .\n")

	cmd := exec.Command("df", "-h", ".")
	out, err := cmd.Output()
	if err != nil {
		logger.WriteString("⚠ Could not check disk space\n")
		return checkResultMsg{index: 3, passed: true, warning: true, detail: "Could not check disk space"}
	}

	lines := strings.Split(string(out), "\n")
	if len(lines) < 2 {
		return checkResultMsg{index: 3, passed: true, warning: true, detail: "Could not parse disk info"}
	}

	fields := strings.Fields(lines[1])
	if len(fields) >= 4 {
		available := fields[3]
		logger.WriteString(fmt.Sprintf("Disk available: %s\n", available))
		return checkResultMsg{index: 3, passed: true, detail: fmt.Sprintf("%s available", available)}
	}

	return checkResultMsg{index: 3, passed: true, detail: "OK"}
}

func (m ChecksModel) checkNetwork() checkResultMsg {
	logger := installer.GetLogger()
	logger.WriteString("$ curl -s https://github.com\n")

	cmd := exec.Command("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "5", "https://github.com")
	out, err := cmd.Output()
	if err != nil || strings.TrimSpace(string(out)) != "200" {
		logger.WriteString("✗ Cannot reach github.com\n")
		return checkResultMsg{index: 4, passed: false, detail: "Cannot reach github.com"}
	}
	logger.WriteString("✓ Connected to github.com\n")
	return checkResultMsg{index: 4, passed: true, detail: "Connected"}
}

func (m ChecksModel) checkDockerVolumes() checkResultMsg {
	logger := installer.GetLogger()

	// Only relevant for upgrades (when posthog dir already exists)
	if !installer.DirExists("posthog") {
		logger.WriteString("New installation, skipping volume check\n")
		return checkResultMsg{index: 5, passed: true, detail: "new install"}
	}

	logger.WriteString("Checking for named Docker volumes...\n")
	hasPostgres, hasClickhouse := installer.CheckDockerVolumes()

	if hasPostgres && hasClickhouse {
		logger.WriteString("✓ Named volumes found\n")
		return checkResultMsg{index: 5, passed: true, detail: "postgres-data, clickhouse-data"}
	}

	// Volumes missing - this is a warning for pre-1.39 installations
	warning := installer.GetVolumeWarning()
	if warning != "" {
		logger.WriteString("⚠ " + warning + "\n")
		return checkResultMsg{index: 5, passed: true, warning: true, detail: "volumes may be anonymous (pre-1.39)"}
	}

	return checkResultMsg{index: 5, passed: true, detail: "OK"}
}

func (m ChecksModel) Update(msg tea.Msg) (ChecksModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		return m, nil

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	case checkResultMsg:
		if msg.passed {
			if msg.warning {
				m.checks[msg.index].status = checkWarning
				m.hasWarnings = true
			} else {
				m.checks[msg.index].status = checkPassed
			}
		} else {
			m.checks[msg.index].status = checkFailed
			m.allGood = false
		}
		m.checks[msg.index].detail = msg.detail

		// Move to next check
		m.current++
		if m.current < len(m.checks) {
			m.checks[m.current].status = checkRunning
			return m, m.runCheck(m.current)
		}

		// All checks done
		m.done = true
		return m, func() tea.Msg {
			time.Sleep(500 * time.Millisecond)
			return allChecksCompleteMsg{}
		}

	case allChecksCompleteMsg:
		if !m.allGood {
			return m, func() tea.Msg {
				return ErrorMsg{Err: fmt.Errorf("system requirements not met")}
			}
		}
		// If no warnings, auto-proceed
		if !m.hasWarnings {
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: nil}
			}
		}
		// If warnings exist, wait for user confirmation
		return m, nil

	case tea.KeyMsg:
		if m.done && m.allGood {
			switch msg.String() {
			case "y", "Y":
				// User explicitly confirmed to proceed despite warnings
				m.confirmed = true
				return m, func() tea.Msg {
					return StepCompleteMsg{Data: nil}
				}
			case "n", "N", "esc":
				// User chose not to proceed
				return m, func() tea.Msg {
					return ErrorMsg{Err: fmt.Errorf("installation cancelled by user")}
				}
			case "enter":
				// Enter only proceeds if no warnings (default N for warnings)
				if !m.hasWarnings {
					return m, func() tea.Msg {
						return StepCompleteMsg{Data: nil}
					}
				}

				// With warnings, enter = N (abort)
				return m, func() tea.Msg {
					return ErrorMsg{Err: fmt.Errorf("installation cancelled by user")}
				}
			}
		}
	}

	return m, nil
}

func (m ChecksModel) View() string {
	var checkLines []string

	for i, check := range m.checks {
		var icon, style string

		switch check.status {
		case checkPending:
			icon = "○"
			style = ui.MutedStyle.Render(check.name)
		case checkRunning:
			icon = m.spinner.View()
			style = ui.BoldStyle.Render(check.name)
		case checkPassed:
			icon = ui.Checkmark()
			style = ui.SuccessStyle.Render(check.name)
		case checkWarning:
			icon = "⚠"
			style = ui.WarningStyle.Render(check.name)
		case checkFailed:
			icon = ui.Cross()
			style = ui.ErrorStyle.Render(check.name)
		}

		line := fmt.Sprintf("  %s %s", icon, style)
		if check.detail != "" && (check.status == checkPassed || check.status == checkFailed || check.status == checkWarning) {
			line += ui.MutedStyle.Render(fmt.Sprintf(" (%s)", check.detail))
		}

		// Start the first check as running
		if i == 0 && check.status == checkPending && m.current == 0 {
			m.checks[0].status = checkRunning
		}

		checkLines = append(checkLines, line)
	}

	var footer string
	if m.done {
		if !m.allGood {
			footer = ui.ErrorStyle.Render("\n✗ Some checks failed. Please resolve the issues and try again.")
		} else if m.hasWarnings {
			footer = lipgloss.JoinVertical(
				lipgloss.Left,
				"",
				ui.WarningStyle.Render("⚠ Some checks have warnings."),
				ui.MutedStyle.Render("Review the warnings above before proceeding."),
				"",
				ui.WarningStyle.Render("Do you want to proceed anyway? [y/N]"),
			)
		} else {
			footer = ui.SuccessStyle.Render("\n✓ All checks passed!")
		}
	}

	// Always show log panel
	logLines := installer.GetLogger().GetLines(5)
	logPanel := ui.RenderLogPanel(logLines, 100, 7)

	content := lipgloss.JoinVertical(
		lipgloss.Left,
		ui.TitleStyle.Render("System Requirements Check"),
		"",
		ui.SubtitleStyle.Render("Checking your system meets the requirements..."),
		"",
		strings.Join(checkLines, "\n"),
		footer,
		"",
		logPanel,
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}
