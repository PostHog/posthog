package steps

import (
	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

type versionMode int

const (
	versionModeSelect versionMode = iota
	versionModeCustom
)

type VersionModel struct {
	mode      versionMode
	selected  int
	options   []string
	values    []string
	textInput textinput.Model
}

func (m VersionModel) IsCustomMode() bool {
	return m.mode == versionModeCustom
}

func NewVersionModel() VersionModel {
	ti := textinput.New()
	ti.Placeholder = "e.g., 1.43.0 or commit hash"
	ti.CharLimit = 64
	ti.Width = 40

	return VersionModel{
		mode:     versionModeSelect,
		selected: 0,
		options: []string{
			"latest (recommended)",
			"latest-release (deprecated, use 'latest' instead)",
			"Enter specific version/commit",
		},
		values: []string{
			"latest",
			"latest-release",
			"",
		},
		textInput: ti,
	}
}

func (m VersionModel) Init() tea.Cmd {
	return nil
}

func (m VersionModel) Update(msg tea.Msg) (VersionModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		if m.mode == versionModeCustom {
			switch msg.String() {
			case "enter":
				if m.textInput.Value() != "" {
					return m, func() tea.Msg {
						return StepCompleteMsg{Data: m.textInput.Value()}
					}
				}
			case "esc":
				m.mode = versionModeSelect
				return m, nil
			}
			var cmd tea.Cmd
			m.textInput, cmd = m.textInput.Update(msg)
			return m, cmd
		}

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
			if m.selected == 2 {
				m.mode = versionModeCustom
				m.textInput.Focus()
				return m, textinput.Blink
			}
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: m.values[m.selected]}
			}
		}
	}
	return m, nil
}

func (m VersionModel) View() string {
	var content string

	if m.mode == versionModeCustom {
		content = lipgloss.JoinVertical(
			lipgloss.Left,
			ui.TitleStyle.Render("Enter PostHog Version"),
			"",
			ui.SubtitleStyle.Render("Enter a version tag or commit hash:"),
			"",
			m.textInput.View(),
			"",
			ui.MutedStyle.Render("Check available versions at:"),
			ui.MutedStyle.Render("https://hub.docker.com/r/posthog/posthog/tags"),
			"",
			ui.HelpStyle.Render("enter confirm • esc back"),
		)
	} else {
		content = lipgloss.JoinVertical(
			lipgloss.Left,
			ui.TitleStyle.Render("Select PostHog Version"),
			"",
			ui.SubtitleStyle.Render("Which version would you like to install?"),
			"",
			ui.RenderMenuItems(m.options, m.selected),
			"",
			ui.MutedStyle.Render("'latest' is recommended for hobby deployments"),
			"",
			ui.HelpStyle.Render("↑/↓ navigate • enter select • esc back"),
		)
	}

	return lipgloss.NewStyle().
		Padding(2, 4).
		Render(content)
}
