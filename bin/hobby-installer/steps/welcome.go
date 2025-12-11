package steps

import (
	"fmt"
	"math/rand"
	"time"

	"github.com/charmbracelet/bubbles/key"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/bin/hobby-installer/installer"
	"github.com/posthog/posthog/bin/hobby-installer/ui"
)

var funFacts = []string{
	"PostHog was founded in January 2020 during Y Combinator",
	"The hedgehog mascot is named Max",
	"PostHog is 100% open source - check out github.com/PostHog/posthog",
	"You can use feature flags to safely roll out changes",
	"Session recordings help you see exactly what users experience",
	"PostHog supports 40+ data integrations out of the box",
	"The name 'PostHog' comes from 'Product OS for Hedgehogs'",
	"You can run SQL queries directly on your PostHog data",
	"PostHog was built by engineers, for engineers",
	"Hedgehogs can run up to 6 miles per hour!",
}

var hedgehogMoods = []string{
	"  /)_/)  \n ( o.o ) \n  > ^ <  ",
	"  /)_/)  \n ( ^.^ ) \n  > ^ <  ",
	"  /)_/)  \n ( >.< ) \n  > ^ <  ",
	"  /)_/)  \n ( o.O ) \n  > ^ <  ",
	"  /)_/)  \n ( -.- ) \n  > ^ <  ",
}

type WelcomeModel struct {
	isUpgrade    bool
	factIndex    int
	hedgehogMood int
	petCount     int
}

func NewWelcomeModel() WelcomeModel {
	rand.Seed(time.Now().UnixNano())
	isUpgrade := installer.DirExists("posthog")
	return WelcomeModel{
		isUpgrade:    isUpgrade,
		factIndex:    rand.Intn(len(funFacts)),
		hedgehogMood: 0,
		petCount:     0,
	}
}

func (m WelcomeModel) Init() tea.Cmd {
	return nil
}

func (m WelcomeModel) IsUpgrade() bool {
	return m.isUpgrade
}

func (m WelcomeModel) Update(msg tea.Msg) (WelcomeModel, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch {
		case key.Matches(msg, key.NewBinding(key.WithKeys("enter"))):
			mode := 0
			if m.isUpgrade {
				mode = 1
			}
			return m, func() tea.Msg {
				return StepCompleteMsg{Data: mode}
			}
		case key.Matches(msg, key.NewBinding(key.WithKeys("left", "h"))):
			m.factIndex--
			if m.factIndex < 0 {
				m.factIndex = len(funFacts) - 1
			}
		case key.Matches(msg, key.NewBinding(key.WithKeys("right", "l"))):
			m.factIndex++
			if m.factIndex >= len(funFacts) {
				m.factIndex = 0
			}
		case key.Matches(msg, key.NewBinding(key.WithKeys(" "))):
			m.petCount++
			m.hedgehogMood = rand.Intn(len(hedgehogMoods))
		}
	}
	return m, nil
}

func (m WelcomeModel) View() string {
	content := lipgloss.JoinVertical(
		lipgloss.Center,
		ui.GetWelcomeArt(),
		"",
		m.renderHedgehog(),
		ui.MutedStyle.Render(m.getPetMessage()),
		"",
		ui.TitleStyle.Render(m.getActionTitle()),
		ui.SubtitleStyle.Render(m.getActionDescription()),
		"",
		m.renderFactBox(),
		m.renderFactNav(),
		"",
		ui.HelpStyle.Render(m.getHelpText()),
	)

	return lipgloss.NewStyle().
		Padding(1, 4).
		Render(content)
}

func (m WelcomeModel) getActionTitle() string {
	if m.isUpgrade {
		return "Upgrade PostHog"
	}
	return "Install PostHog"
}

func (m WelcomeModel) getActionDescription() string {
	if m.isUpgrade {
		return "Existing installation detected. Ready to upgrade."
	}

	return "Ready to install PostHog self-hosted."
}

func (m WelcomeModel) getPetMessage() string {
	switch {
	case m.petCount == 0:
		return "Press space to pet the hedgehog"
	case m.petCount == 1:
		return "The hedgehog seems happy!"
	case m.petCount < 5:
		return fmt.Sprintf("You've pet the hedgehog %d times", m.petCount)
	case m.petCount < 10:
		return "The hedgehog really likes you!"
	default:
		return fmt.Sprintf("Best friends! (%d pets)", m.petCount)
	}
}

func (m WelcomeModel) getHelpText() string {
	return "enter continue • arrows cycle facts • space pet hedgehog • esc quit"
}

func (m WelcomeModel) renderHedgehog() string {
	return lipgloss.NewStyle().
		Foreground(ui.ColorPrimary).
		Render(hedgehogMoods[m.hedgehogMood])
}

func (m WelcomeModel) renderFactBox() string {
	return lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(ui.ColorMuted).
		Padding(0, 2).
		Width(60).
		Align(lipgloss.Center).
		Render(fmt.Sprintf("Did you know?\n%s", funFacts[m.factIndex]))
}

func (m WelcomeModel) renderFactNav() string {
	return ui.MutedStyle.Render(fmt.Sprintf("< %d/%d >", m.factIndex+1, len(funFacts)))
}
