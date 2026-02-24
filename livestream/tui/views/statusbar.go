package views

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
)

type ConnectionState int

const (
	StateConnected ConnectionState = iota
	StateDisconnected
	StateReconnecting
	StateAuthenticating
)

type StatusBarView struct {
	connState        ConnectionState
	teamName         string
	paused           bool
	width            int
	viewMode         string
	eventTypeFilter  string
	distinctIDFilter string
}

func NewStatusBarView() *StatusBarView {
	return &StatusBarView{
		connState: StateDisconnected,
	}
}

func (v *StatusBarView) SetSize(w int) {
	v.width = w
}

func (v *StatusBarView) SetState(state ConnectionState) {
	v.connState = state
}

func (v *StatusBarView) SetTeamName(name string) {
	v.teamName = name
}

func (v *StatusBarView) SetPaused(p bool) {
	v.paused = p
}

func (v *StatusBarView) SetViewMode(mode string) {
	v.viewMode = mode
}

func (v *StatusBarView) SetFilters(eventType, distinctID string) {
	v.eventTypeFilter = eventType
	v.distinctIDFilter = distinctID
}

func (v *StatusBarView) ViewHeader() string {
	headerStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("#FFFFFF")).
		Background(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"}).
		Padding(0, 1)

	connectedStyle := lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#388E3C", Dark: "#77B96C"}).Bold(true)
	disconnectedStyle := lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#D32F2F", Dark: "#EF5350"}).Bold(true)
	reconnectingStyle := lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#F57C00", Dark: "#FFB74D"}).Bold(true)
	pausedStyle := lipgloss.NewStyle().Foreground(lipgloss.AdaptiveColor{Light: "#F57C00", Dark: "#FFB74D"}).Bold(true)

	logoColors := []lipgloss.Color{"#1D4AFF", "#F54E00", "#F9BD2B", "#1D1F27"}
	logo := ""
	for _, c := range logoColors {
		logo += lipgloss.NewStyle().Background(c).Render(" ")
	}

	title := headerStyle.Render(" PostHog Live ") + " " + logo

	var state string
	switch v.connState {
	case StateConnected:
		state = connectedStyle.Render("Connected")
	case StateDisconnected:
		state = disconnectedStyle.Render("Disconnected")
	case StateReconnecting:
		state = reconnectingStyle.Render("Reconnecting...")
	case StateAuthenticating:
		state = reconnectingStyle.Render("Authenticating...")
	}

	if v.paused {
		state += " " + pausedStyle.Render("[PAUSED]")
	}

	filterStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#1D4AFF", Dark: "#1D4AFF"})
	filterLabelStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})

	hintStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#AAAAAA", Dark: "#555555"})

	filters := ""
	if v.eventTypeFilter != "" {
		filters += " " + filterLabelStyle.Render("event:") + filterStyle.Render(v.eventTypeFilter) + hintStyle.Render(" [f]")
	}
	if v.distinctIDFilter != "" {
		filters += " " + filterLabelStyle.Render("id:") + filterStyle.Render(v.distinctIDFilter) + hintStyle.Render(" [d]")
	}

	team := ""
	if v.teamName != "" {
		team = lipgloss.NewStyle().
			Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"}).
			Render(fmt.Sprintf("Team: %s", v.teamName))
	}

	// Right-align team name
	gap := v.width - lipgloss.Width(title) - lipgloss.Width(state) - lipgloss.Width(filters) - lipgloss.Width(team) - 4
	if gap < 1 {
		gap = 1
	}

	spaces := lipgloss.NewStyle().Width(gap).Render("")

	return title + "  " + state + filters + spaces + team
}

func (v *StatusBarView) ViewFooter() string {
	keyStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"}).
		Bold(true)
	descStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})

	footerStyle := lipgloss.NewStyle().
		Padding(0, 1).
		Width(v.width)

	var bindings []struct{ key, desc string }
	switch v.viewMode {
	case "detail":
		bindings = []struct{ key, desc string }{
			{"esc", "back"},
			{"j/k", "scroll"},
			{"q", "quit"},
		}
	default:
		bindings = []struct{ key, desc string }{
			{"p", "pause"},
			{"f", "filter event"},
			{"d", "distinct ID"},
			{"c", "columns"},
			{"?", "help"},
			{"enter", "detail"},
			{"x", "clear"},
			{"q", "quit"},
		}
	}

	var parts []string
	for _, b := range bindings {
		parts = append(parts, keyStyle.Render("["+b.key+"]")+" "+descStyle.Render(b.desc))
	}

	content := ""
	for i, p := range parts {
		if i > 0 {
			content += descStyle.Render(" • ")
		}
		content += p
	}

	return footerStyle.Render(content)
}
