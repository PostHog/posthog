package views

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
)

type StatsView struct {
	usersOnProduct   int
	activeRecordings int
	eventsPerMin int
	width        int
}

func NewStatsView() *StatsView {
	return &StatsView{}
}

func (v *StatsView) SetSize(w int) {
	v.width = w
}

func (v *StatsView) Update(users, recordings int) {
	v.usersOnProduct = users
	v.activeRecordings = recordings
}

func (v *StatsView) SetEventRate(count int) {
	v.eventsPerMin = count
}

func (v *StatsView) View() string {
	labelStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})
	valueStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.AdaptiveColor{Light: "#1D1F27", Dark: "#EDEDEC"})

	borderStyle := lipgloss.NewStyle().
		Border(lipgloss.NormalBorder(), false, false, true, false).
		BorderForeground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"}).
		Padding(0, 1).
		Width(v.width)

	users := labelStyle.Render("Active users: ") + valueStyle.Render(fmt.Sprintf("%d", v.usersOnProduct))
	recordings := labelStyle.Render("Active recordings: ") + valueStyle.Render(fmt.Sprintf("%d", v.activeRecordings))
	events := labelStyle.Render("Events/min: ") + valueStyle.Render(fmt.Sprintf("%d", v.eventsPerMin))

	content := lipgloss.JoinHorizontal(lipgloss.Center,
		users, "      ", recordings, "      ", events,
	)

	return borderStyle.Render(content)
}
