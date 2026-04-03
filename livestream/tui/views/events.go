package views

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/livestream/tui/sse"
)

const maxEvents = 200

type PropColumn struct {
	Name  string
	Width int
}

func (c PropColumn) String() string {
	name := c.Name
	if strings.Contains(name, ":") || strings.Contains(name, ",") {
		name = `"` + name + `"`
	}
	return fmt.Sprintf("%s:%d", name, c.Width)
}

var defaultPropertyColumns = []PropColumn{
	{Name: "$current_url", Width: 40},
}

type EventsView struct {
	events          []sse.EventMsg
	cursor          int
	offset          int
	width           int
	height          int
	paused          bool
	selected        int
	propertyColumns []PropColumn
}

func NewEventsView() *EventsView {
	return &EventsView{
		events:          make([]sse.EventMsg, 0, maxEvents),
		cursor:          0,
		offset:          0,
		selected:        -1,
		propertyColumns: defaultPropertyColumns,
	}
}

func (v *EventsView) SetPropertyColumns(cols []PropColumn) {
	if len(cols) == 0 {
		v.propertyColumns = defaultPropertyColumns
		return
	}
	v.propertyColumns = cols
}

// ColumnsExceedWidth returns true if the given columns would make the table
// wider than the current terminal width.
func (v *EventsView) ColumnsExceedWidth(cols []PropColumn) bool {
	if v.width == 0 {
		return false
	}
	return columnsWidth(cols) > v.width
}

// Fixed columns: prefix(1) + event(30) + gap(2) + distinct(40) + gap(2) + time(8) + gap(2) = 85
const fixedColumnsWidth = 85

func columnsWidth(cols []PropColumn) int {
	w := fixedColumnsWidth
	for _, c := range cols {
		w += 2 + c.Width
	}
	return w
}

func (v *EventsView) PropertyColumns() []PropColumn {
	return v.propertyColumns
}

func (v *EventsView) PropertyColumnsString() string {
	parts := make([]string, len(v.propertyColumns))
	for i, c := range v.propertyColumns {
		parts[i] = c.String()
	}
	return strings.Join(parts, ",")
}

func (v *EventsView) AddEvent(e sse.EventMsg) {
	if v.paused {
		return
	}
	v.events = append(v.events, e)
	if len(v.events) > maxEvents {
		// In-place compaction: copy last maxEvents to the front, zero old slots
		// so the GC can collect the Properties maps, then reset length.
		n := copy(v.events, v.events[len(v.events)-maxEvents:])
		for i := n; i < len(v.events); i++ {
			v.events[i] = sse.EventMsg{}
		}
		v.events = v.events[:n]
	}
	// Auto-scroll to bottom if user hasn't scrolled up
	if v.cursor == len(v.events)-2 || v.cursor == 0 {
		v.cursor = len(v.events) - 1
	}
}

func (v *EventsView) Clear() {
	v.events = v.events[:0]
	v.cursor = 0
	v.offset = 0
	v.selected = -1
}

func (v *EventsView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

func (v *EventsView) SetPaused(p bool) {
	v.paused = p
}

func (v *EventsView) MoveUp() {
	if v.cursor > 0 {
		v.cursor--
	}
}

func (v *EventsView) MoveDown() {
	if v.cursor < len(v.events)-1 {
		v.cursor++
	}
}

func (v *EventsView) Select() int {
	if v.cursor >= 0 && v.cursor < len(v.events) {
		v.selected = v.cursor
		return v.selected
	}
	return -1
}

func (v *EventsView) SelectedEvent() *sse.EventMsg {
	if v.selected >= 0 && v.selected < len(v.events) {
		return &v.events[v.selected]
	}
	return nil
}

func (v *EventsView) Deselect() {
	v.selected = -1
}

func (v *EventsView) EventCount() int {
	return len(v.events)
}

func relativeTime(t time.Time) string {
	d := time.Since(t)
	switch {
	case d < time.Second:
		return "now"
	case d < time.Minute:
		return fmt.Sprintf("%ds ago", int(d.Seconds()))
	case d < time.Hour:
		return fmt.Sprintf("%dm ago", int(d.Minutes()))
	default:
		return fmt.Sprintf("%dh ago", int(d.Hours()))
	}
}

func prettyPropHeader(prop string) string {
	name := strings.TrimPrefix(prop, "$")
	name = strings.ReplaceAll(name, "_", " ")
	if len(name) > 0 {
		name = strings.ToUpper(name[:1]) + name[1:]
	}
	return name
}

func (v *EventsView) View() string {
	if v.width == 0 || v.height == 0 {
		return ""
	}

	headerStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
		Background(lipgloss.AdaptiveColor{Light: "#1D4AFF", Dark: "#1D4AFF"})

	cursorStyle := lipgloss.NewStyle().
		Background(lipgloss.AdaptiveColor{Light: "#DDE4FF", Dark: "#2A2F4A"}).
		Foreground(lipgloss.AdaptiveColor{Light: "#1D1F27", Dark: "#EDEDEC"})

	mutedStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})

	colEvent := 30
	colDistinct := 40
	colTime := 8

	// Build header
	header := fmt.Sprintf(" %-*s  %-*s", colEvent, "Event", colDistinct, "Distinct ID")
	for _, col := range v.propertyColumns {
		header += fmt.Sprintf("  %-*s", col.Width, prettyPropHeader(col.Name))
	}
	header += fmt.Sprintf("  %-*s", colTime, "Time")
	header = headerStyle.Width(v.width).Render(header)

	visibleRows := v.height - 2
	if visibleRows < 1 {
		visibleRows = 1
	}

	// Adjust offset so cursor is always visible
	if v.cursor < v.offset {
		v.offset = v.cursor
	}
	if v.cursor >= v.offset+visibleRows {
		v.offset = v.cursor - visibleRows + 1
	}

	var rows []string
	for i := v.offset; i < len(v.events) && i < v.offset+visibleRows; i++ {
		e := v.events[i]

		eventName := truncate(e.Event, colEvent)
		distinctID := truncate(e.DistinctID, colDistinct)
		timeStr := relativeTime(e.ReceivedAt)

		prefix := " "
		if i == v.cursor {
			prefix = "▸"
		}

		row := fmt.Sprintf("%s%-*s  %-*s", prefix, colEvent, eventName, colDistinct, distinctID)
		for _, col := range v.propertyColumns {
			val := ""
			if props := e.Properties; props != nil {
				if v, ok := props[col.Name]; ok && v != nil {
					val = fmt.Sprint(v)
				}
			}
			row += fmt.Sprintf("  %-*s", col.Width, truncate(val, col.Width))
		}
		row += fmt.Sprintf("  %-*s", colTime, timeStr)

		if i == v.cursor {
			row = cursorStyle.Width(v.width).Render(row)
		} else {
			row = lipgloss.NewStyle().Width(v.width).Render(row)
		}
		rows = append(rows, row)
	}

	// Fill remaining rows
	for i := len(rows); i < visibleRows; i++ {
		rows = append(rows, strings.Repeat(" ", v.width))
	}

	if len(v.events) == 0 {
		empty := mutedStyle.Render("  Waiting for events...")
		rows[0] = lipgloss.NewStyle().Width(v.width).Render(empty)
	}

	return header + "\n" + strings.Join(rows, "\n")
}

func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	if maxLen <= 3 {
		return s[:maxLen]
	}
	return s[:maxLen-3] + "..."
}
