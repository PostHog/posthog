package views

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/livestream/tui/sse"
)

type DetailView struct {
	event    *sse.EventMsg
	scroll   int
	width    int
	height   int
	lines    []string
	visible  bool
}

func NewDetailView() *DetailView {
	return &DetailView{}
}

func (v *DetailView) SetEvent(e *sse.EventMsg) {
	v.event = e
	v.scroll = 0
	v.visible = e != nil
	v.buildLines()
}

func (v *DetailView) SetSize(w, h int) {
	v.width = w
	v.height = h
}

func (v *DetailView) IsVisible() bool {
	return v.visible
}

func (v *DetailView) Close() {
	v.visible = false
	v.event = nil
}

func (v *DetailView) ScrollUp() {
	if v.scroll > 0 {
		v.scroll--
	}
}

func (v *DetailView) ScrollDown() {
	maxScroll := len(v.lines) - v.contentHeight()
	if maxScroll < 0 {
		maxScroll = 0
	}
	if v.scroll < maxScroll {
		v.scroll++
	}
}

func (v *DetailView) contentHeight() int {
	h := v.height - 6
	if h < 1 {
		h = 1
	}
	return h
}

func (v *DetailView) buildLines() {
	if v.event == nil {
		v.lines = nil
		return
	}

	keyStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#1D4AFF", Dark: "#1D4AFF"}).
		Bold(true)
	valStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#1D1F27", Dark: "#EDEDEC"})

	var lines []string
	lines = append(lines, keyStyle.Render("Event: ")+valStyle.Render(v.event.Event))
	lines = append(lines, keyStyle.Render("UUID: ")+valStyle.Render(v.event.UUID))
	lines = append(lines, keyStyle.Render("Distinct ID: ")+valStyle.Render(v.event.DistinctID))
	lines = append(lines, keyStyle.Render("Person ID: ")+valStyle.Render(v.event.PersonID))
	lines = append(lines, keyStyle.Render("Timestamp: ")+valStyle.Render(fmt.Sprint(v.event.Timestamp)))
	lines = append(lines, "")
	lines = append(lines, keyStyle.Render("Properties:"))

	if v.event.Properties != nil {
		// border (2) + padding (2*2) + indent (2) = 8 chars of overhead
		maxValWidth := v.width - 8
		if maxValWidth < 20 {
			maxValWidth = 20
		}

		keys := make([]string, 0, len(v.event.Properties))
		for k := range v.event.Properties {
			keys = append(keys, k)
		}
		sort.Strings(keys)

		for _, k := range keys {
			val := v.event.Properties[k]
			valStr := formatValue(val)
			// key prefix takes up space: "  " + key + ": "
			available := maxValWidth - len(k) - 4
			if available < 10 {
				available = 10
			}
			if len(valStr) > available {
				valStr = valStr[:available-3] + "..."
			}
			lines = append(lines, "  "+keyStyle.Render(k+": ")+valStyle.Render(valStr))
		}
	}

	v.lines = lines
}

func formatValue(v interface{}) string {
	switch val := v.(type) {
	case string:
		return val
	case nil:
		return "null"
	default:
		b, err := json.Marshal(val)
		if err != nil {
			return fmt.Sprint(val)
		}
		return string(b)
	}
}

func (v *DetailView) View() string {
	if !v.visible || v.event == nil {
		return ""
	}

	borderStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"}).
		Padding(1, 2).
		Width(v.width - 4).
		Height(v.height - 2)

	titleStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.AdaptiveColor{Light: "#F54E00", Dark: "#F54E00"})

	ch := v.contentHeight()
	end := v.scroll + ch
	if end > len(v.lines) {
		end = len(v.lines)
	}
	start := v.scroll
	if start > len(v.lines) {
		start = len(v.lines)
	}

	hintStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})

	visible := v.lines[start:end]
	title := titleStyle.Render("Event Detail") + "  " + hintStyle.Render("(esc to go back, j/k to scroll)")
	content := title + "\n\n" + strings.Join(visible, "\n")

	return borderStyle.Render(content)
}
