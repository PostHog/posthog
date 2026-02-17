package views

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/livestream/tui/sse"
)

const geoWindowDuration = 60 * time.Second

type geoEntry struct {
	country   string
	count     uint
	expiresAt time.Time
}

type GeoView struct {
	entries     []geoEntry
	width       int
	lastPrune   time.Time
	lastRender  time.Time
	cachedView  string
	cachedWidth int
}

func NewGeoView() *GeoView {
	return &GeoView{
		lastPrune: time.Now(),
	}
}

func (v *GeoView) SetSize(w int) {
	v.width = w
}

func (v *GeoView) Clear() {
	v.entries = v.entries[:0]
	v.cachedView = ""
}

const maxGeoEntries = 8192

func (v *GeoView) AddEvent(e sse.GeoEventMsg) {
	now := time.Now()
	if len(v.entries) >= maxGeoEntries {
		v.prune(now)
	}
	v.entries = append(v.entries, geoEntry{
		country:   e.CountryCode,
		count:     e.Count,
		expiresAt: now.Add(geoWindowDuration),
	})
}

func (v *GeoView) prune(now time.Time) {
	n := 0
	for _, e := range v.entries {
		if now.Before(e.expiresAt) {
			v.entries[n] = e
			n++
		}
	}
	for i := n; i < len(v.entries); i++ {
		v.entries[i] = geoEntry{}
	}
	v.entries = v.entries[:n]
	v.lastPrune = now
}

func countryFlag(code string) string {
	if len(code) != 2 {
		return code
	}
	code = strings.ToUpper(code)
	r0 := rune(code[0]) - 'A' + 0x1F1E6
	r1 := rune(code[1]) - 'A' + 0x1F1E6
	return string([]rune{r0, r1})
}

func countryColorIndex(code string) int {
	h := 0
	for _, c := range code {
		h = h*31 + int(c)
	}
	if h < 0 {
		h = -h
	}
	return h % len(countryColors)
}

type countryCount struct {
	country string
	count   uint
}

func (v *GeoView) aggregated() []countryCount {
	now := time.Now()
	if now.Sub(v.lastPrune) > 5*time.Second {
		v.prune(now)
	}

	counts := make(map[string]uint)
	for _, e := range v.entries {
		if now.Before(e.expiresAt) {
			counts[e.country] += e.count
		}
	}

	sorted := make([]countryCount, 0, len(counts))
	for country, count := range counts {
		sorted = append(sorted, countryCount{country, count})
	}
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].count != sorted[j].count {
			return sorted[i].count > sorted[j].count
		}
		return sorted[i].country < sorted[j].country
	})
	return sorted
}

var countryColors = []lipgloss.Color{
	"#F54E00", // PostHog orange
	"#1D4AFF", // PostHog blue
	"#77B96C", // green
	"#E040FB", // purple
	"#00BCD4", // cyan
	"#FF9800", // amber
	"#E91E63", // pink
	"#8BC34A", // light green
}

func (v *GeoView) View() string {
	now := time.Now()
	if v.cachedView != "" && v.cachedWidth == v.width && now.Sub(v.lastRender) < 2*time.Second {
		return v.cachedView
	}
	v.lastRender = now
	v.cachedWidth = v.width

	sorted := v.aggregated()

	separatorStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#CCCCCC", Dark: "#444444"})
	countStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#555555", Dark: "#999999"})
	emptyStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})

	barStyle := lipgloss.NewStyle().
		Border(lipgloss.NormalBorder(), true, false, false, false).
		BorderForeground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#444444"}).
		Width(v.width)

	labelStyle := lipgloss.NewStyle().
		Foreground(lipgloss.AdaptiveColor{Light: "#888888", Dark: "#666666"})

	label := labelStyle.Render("Events by country/min: ")
	labelWidth := lipgloss.Width(label)

	if len(sorted) == 0 {
		v.cachedView = barStyle.Render(" " + label + emptyStyle.Render("waiting for data"))
		return v.cachedView
	}

	separator := separatorStyle.Render("  ·  ")
	separatorWidth := lipgloss.Width(separator)

	contentWidth := v.width - 2 - labelWidth
	var parts []string
	usedWidth := 0

	for _, cc := range sorted {
		colorIdx := countryColorIndex(cc.country)
		nameStyle := lipgloss.NewStyle().
			Foreground(countryColors[colorIdx]).
			Bold(true)

		flag := countryFlag(cc.country)
		entry := flag + " " + nameStyle.Render(cc.country) + countStyle.Render(fmt.Sprintf("(%d)", cc.count))
		entryWidth := lipgloss.Width(entry)

		needed := entryWidth
		if len(parts) > 0 {
			needed += separatorWidth
		}

		if usedWidth+needed > contentWidth {
			break
		}

		if len(parts) > 0 {
			parts = append(parts, separator)
			usedWidth += separatorWidth
		}
		parts = append(parts, entry)
		usedWidth += entryWidth
	}

	content := " " + label + strings.Join(parts, "")

	visibleWidth := lipgloss.Width(content)
	if visibleWidth < v.width {
		content += strings.Repeat(" ", v.width-visibleWidth)
	}

	v.cachedView = barStyle.Render(content)
	return v.cachedView
}
