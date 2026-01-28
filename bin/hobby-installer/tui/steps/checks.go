package steps

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/core"
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
	coreChecks  []core.Check
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

	coreChecks := core.GetChecks()
	checks := make([]systemCheck, len(coreChecks))
	for i, c := range coreChecks {
		checks[i] = systemCheck{name: c.Name, status: checkPending}
	}

	return ChecksModel{
		checks:     checks,
		coreChecks: coreChecks,
		current:    0,
		spinner:    s,
		done:       false,
		allGood:    true,
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
		time.Sleep(300 * time.Millisecond)

		if index >= len(m.coreChecks) {
			return nil
		}

		result := m.coreChecks[index].Run()
		return checkResultMsg{
			index:   index,
			passed:  result.Passed && result.Err == nil,
			warning: result.Warning,
			detail:  m.getDetail(result),
		}
	}
}

func (m ChecksModel) getDetail(result core.CheckResult) string {
	if result.Err != nil {
		return result.Err.Error()
	}
	return result.Detail
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

		m.current++
		if m.current < len(m.checks) {
			m.checks[m.current].status = checkRunning
			return m, m.runCheck(m.current)
		}

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
		if !m.hasWarnings {
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: nil}
			}
		}
		return m, nil

	case tea.KeyMsg:
		if m.done && m.allGood {
			switch msg.String() {
			case "y", "Y":
				m.confirmed = true
				return m, func() tea.Msg {
					return StepCompleteMsg{Data: nil}
				}
			case "n", "N", "esc":
				return m, func() tea.Msg {
					return ErrorMsg{Err: fmt.Errorf("installation cancelled by user")}
				}
			case "enter":
				if !m.hasWarnings {
					return m, func() tea.Msg {
						return StepCompleteMsg{Data: nil}
					}
				}
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

	logLines := core.GetLogger().GetLines(5)
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
