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
	checks  []systemCheck
	current int
	spinner spinner.Model
	done    bool
	allGood bool
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
		}
		return nil
	}
}

func (m ChecksModel) checkDocker() checkResultMsg {
	_, err := exec.LookPath("docker")
	if err != nil {
		return checkResultMsg{index: 0, passed: false, detail: "Docker not found in PATH"}
	}

	cmd := exec.Command("docker", "info")
	if err := cmd.Run(); err != nil {
		return checkResultMsg{index: 0, passed: false, detail: "Docker daemon not running"}
	}

	return checkResultMsg{index: 0, passed: true, detail: "Docker is running"}
}

func (m ChecksModel) checkDockerCompose() checkResultMsg {
	// Check for docker-compose or docker compose
	_, err := exec.LookPath("docker-compose")
	if err == nil {
		return checkResultMsg{index: 1, passed: true, detail: "docker-compose available"}
	}

	cmd := exec.Command("docker", "compose", "version")
	if err := cmd.Run(); err == nil {
		return checkResultMsg{index: 1, passed: true, detail: "docker compose available"}
	}

	return checkResultMsg{index: 1, passed: false, detail: "Docker Compose not found"}
}

func (m ChecksModel) checkMemory() checkResultMsg {
	// Try to get memory info (Linux-specific, will be run on Ubuntu)
	scale := int64(1024 * 1024) // Linux command will return KiB
	cmd := exec.Command("sh", "-c", "grep MemTotal /proc/meminfo | awk '{print $2}'")
	out, err := cmd.Output()

	if err != nil || string(out) == "" {
		// On macOS during development, use sysctl
		scale = int64(1024 * 1024 * 1024) // macOS command will return bytes (B)
		cmd = exec.Command("sysctl", "-n", "hw.memsize")
		out, err = cmd.Output()

		if err != nil || string(out) == "" {
			return checkResultMsg{index: 2, passed: true, warning: true, detail: "Could not check memory"}
		}
	}

	memKB, _ := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
	memGB := memKB / scale

	if memGB < 8 {
		return checkResultMsg{index: 2, passed: true, warning: true, detail: fmt.Sprintf("%dGB (8GB+ recommended)", memGB)}
	}
	return checkResultMsg{index: 2, passed: true, detail: fmt.Sprintf("%dGB available", memGB)}
}

func (m ChecksModel) checkDiskSpace() checkResultMsg {
	cmd := exec.Command("df", "-h", ".")
	out, err := cmd.Output()
	if err != nil {
		return checkResultMsg{index: 3, passed: true, warning: true, detail: "Could not check disk space"}
	}

	lines := strings.Split(string(out), "\n")
	if len(lines) < 2 {
		return checkResultMsg{index: 3, passed: true, warning: true, detail: "Could not parse disk info"}
	}

	fields := strings.Fields(lines[1])
	if len(fields) >= 4 {
		available := fields[3]
		return checkResultMsg{index: 3, passed: true, detail: fmt.Sprintf("%s available", available)}
	}

	return checkResultMsg{index: 3, passed: true, detail: "OK"}
}

func (m ChecksModel) checkNetwork() checkResultMsg {
	cmd := exec.Command("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "5", "https://github.com")
	out, err := cmd.Output()
	if err != nil || strings.TrimSpace(string(out)) != "200" {
		return checkResultMsg{index: 4, passed: false, detail: "Cannot reach github.com"}
	}
	return checkResultMsg{index: 4, passed: true, detail: "Connected"}
}

func (m ChecksModel) Update(msg tea.Msg) (ChecksModel, tea.Cmd) {
	switch msg := msg.(type) {
	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	case checkResultMsg:
		if msg.passed {
			if msg.warning {
				m.checks[msg.index].status = checkWarning
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
		if m.allGood {
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: nil}
			}
		}
		return m, func() tea.Msg {
			return ErrorMsg{Err: fmt.Errorf("system requirements not met")}
		}

	case tea.KeyMsg:
		if msg.String() == "enter" && m.done && m.allGood {
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: nil}
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
		if m.allGood {
			footer = ui.SuccessStyle.Render("\n✓ All checks passed! Press enter to continue...")
		} else {
			footer = ui.ErrorStyle.Render("\n✗ Some checks failed. Please resolve the issues and try again.")
		}
	}

	content := lipgloss.JoinVertical(
		lipgloss.Left,
		ui.TitleStyle.Render("System Requirements Check"),
		"",
		ui.SubtitleStyle.Render("Checking your system meets the requirements..."),
		"",
		strings.Join(checkLines, "\n"),
		footer,
	)

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}
