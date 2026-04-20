package main

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/livestream/tui/config"
	"github.com/posthog/posthog/livestream/tui/debug"
	"github.com/posthog/posthog/livestream/tui/sse"
	"github.com/posthog/posthog/livestream/tui/views"
)

type viewMode int

const (
	modeEvents viewMode = iota
	modeDetail
	modeFilterEvent
	modeFilterDistinct
	modeFilterColumns
	modeHelp
)

type App struct {
	creds   *config.Credentials
	client  *sse.Client
	ctx     context.Context
	cancel  context.CancelFunc
	geoOnly bool

	// SSE streams (goroutine-managed)
	eventsStream *sse.Stream
	geoStream    *sse.Stream

	// State
	mode      viewMode
	connected bool
	paused    bool

	// Events/min: count per second, sliding window of last 60 seconds
	eventsThisSecond int
	rateBuckets      []int

	// Reusable flush buffers — swapped with streams each tick, zero-alloc after warmup
	eventBuf []sse.EventMsg
	geoBuf   []sse.GeoEventMsg

	// Filter
	eventTypeFilter  string
	distinctIDFilter string
	filterInput      textinput.Model

	// Views
	events    *views.EventsView
	detail    *views.DetailView
	stats     *views.StatsView
	geo       *views.GeoView
	statusbar *views.StatusBarView
	help      *views.HelpView

	// Temporary warning message
	warning       string
	warningExpiry time.Time

	// Terminal size
	width  int
	height int
}

func NewApp(creds *config.Credentials, eventType, distinctID string, geoOnly bool) *App {
	ctx, cancel := context.WithCancel(context.Background())

	client := sse.NewClient(
		creds.LivestreamHost,
		creds.Token,
		eventType,
		distinctID,
		geoOnly,
	)

	ti := textinput.New()
	ti.CharLimit = 200

	app := &App{
		creds:            creds,
		client:           client,
		ctx:              ctx,
		cancel:           cancel,
		geoOnly:          geoOnly,
		mode:             modeEvents,
		eventTypeFilter:  eventType,
		distinctIDFilter: distinctID,
		filterInput:      ti,
		eventBuf:         make([]sse.EventMsg, 0, 128),
		geoBuf:           make([]sse.GeoEventMsg, 0, 128),
		events:           views.NewEventsView(),
		detail:           views.NewDetailView(),
		stats:            views.NewStatsView(),
		geo:              views.NewGeoView(),
		statusbar:        views.NewStatusBarView(),
		help:             views.NewHelpView(),
	}

	if cfg := config.Load(); len(cfg.Columns) > 0 {
		cols := make([]views.PropColumn, len(cfg.Columns))
		for i, c := range cfg.Columns {
			cols[i] = views.PropColumn{Name: c.Name, Width: c.Width}
		}
		app.events.SetPropertyColumns(cols)
	}

	return app
}

// flushTickMsg fires every 100ms to drain buffered events from the SSE streams.
type flushTickMsg struct{}

type rateResetMsg struct{}

func (a *App) Init() tea.Cmd {
	a.statusbar.SetTeamName(a.creds.TeamName)
	a.statusbar.SetFilters(a.eventTypeFilter, a.distinctIDFilter)

	a.eventsStream = sse.NewStream(a.client, false, a.ctx)
	a.geoStream = sse.NewStream(a.client, true, a.ctx)

	return tea.Batch(
		a.client.PollStats(a.ctx),
		tea.Tick(100*time.Millisecond, func(_ time.Time) tea.Msg {
			return flushTickMsg{}
		}),
		tea.Tick(time.Second, func(_ time.Time) tea.Msg {
			return rateResetMsg{}
		}),
	)
}

func (a *App) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		debug.Log("key", "%s", msg.String())
		return a.handleKey(msg)

	case tea.WindowSizeMsg:
		debug.Log("resize", "width=%d height=%d", msg.Width, msg.Height)
		a.width = msg.Width
		a.height = msg.Height
		a.resize()
		return a, nil

	case flushTickMsg:
		a.flushStreams()
		return a, tea.Tick(100*time.Millisecond, func(_ time.Time) tea.Msg {
			return flushTickMsg{}
		})

	case sse.StatsMsg:
		a.stats.Update(msg.UsersOnProduct, msg.ActiveRecordings)
		return a, a.client.PollStats(a.ctx)

	case sse.StatsErrorMsg:
		return a, a.client.PollStats(a.ctx)

	case sse.PollStatsMsg:
		return a, sse.FetchStats(msg)

	case rateResetMsg:
		a.rateBuckets = append(a.rateBuckets, a.eventsThisSecond)
		if len(a.rateBuckets) > 60 {
			a.rateBuckets = a.rateBuckets[len(a.rateBuckets)-60:]
		}
		a.eventsThisSecond = 0
		total := 0
		for _, b := range a.rateBuckets {
			total += b
		}
		rate := total * 60 / len(a.rateBuckets)
		a.stats.SetEventRate(rate)
		return a, tea.Tick(time.Second, func(_ time.Time) tea.Msg {
			return rateResetMsg{}
		})
	}

	return a, nil
}

// flushStreams drains both SSE streams' buffers in one go — called every 100ms.
// Uses a swap pattern: we give the stream our old (processed) buffer and get
// back the new batch. After warmup this is zero-allocation.
func (a *App) flushStreams() {
	events, evtState := a.eventsStream.FlushEvents(a.eventBuf)
	if evtState != nil {
		a.applyStreamState(*evtState)
	}
	for i := range events {
		a.events.AddEvent(events[i])
	}
	a.eventsThisSecond += len(events)
	a.eventBuf = events

	geos, geoState := a.geoStream.FlushGeo(a.geoBuf)
	if geoState != nil {
		a.applyStreamState(*geoState)
	}
	for i := range geos {
		a.geo.AddEvent(geos[i])
	}
	a.geoBuf = geos
}

func (a *App) applyStreamState(msg sse.StreamStateMsg) {
	stream := "events"
	if msg.GeoOnly {
		stream = "geo"
	}
	if msg.Connected {
		debug.Log("app", "%s stream connected", stream)
	} else if msg.Reconnecting {
		debug.Log("app", "%s stream reconnecting (attempt %d)", stream, msg.Attempt)
	} else {
		debug.Log("app", "%s stream disconnected", stream)
	}
	if !msg.GeoOnly {
		a.connected = msg.Connected
		if msg.Connected {
			a.statusbar.SetState(views.StateConnected)
		} else if msg.Reconnecting {
			a.statusbar.SetState(views.StateReconnecting)
		} else {
			a.statusbar.SetState(views.StateDisconnected)
		}
	}
}

func (a *App) handleKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if a.mode == modeFilterEvent || a.mode == modeFilterDistinct || a.mode == modeFilterColumns {
		return a.handleFilterKey(msg)
	}

	switch {
	case msg.String() == "q" || msg.String() == "ctrl+c":
		a.eventsStream.Stop()
		a.geoStream.Stop()
		a.cancel()
		return a, tea.Quit

	case msg.String() == "p":
		a.paused = !a.paused
		a.events.SetPaused(a.paused)
		a.statusbar.SetPaused(a.paused)
		return a, nil

	case msg.String() == "f":
		a.mode = modeFilterEvent
		a.filterInput.Placeholder = "Event type filter (e.g. $pageview)"
		a.filterInput.SetValue(a.eventTypeFilter)
		a.filterInput.Focus()
		return a, textinput.Blink

	case msg.String() == "d":
		a.mode = modeFilterDistinct
		a.filterInput.Placeholder = "Distinct ID filter"
		a.filterInput.SetValue(a.distinctIDFilter)
		a.filterInput.Focus()
		return a, textinput.Blink

	case msg.String() == "c":
		a.mode = modeFilterColumns
		a.filterInput.Placeholder = `name[:width],... (e.g. $current_url,$browser:15) default width: 40`
		a.filterInput.SetValue(a.events.PropertyColumnsString())
		a.filterInput.Focus()
		return a, textinput.Blink

	case msg.String() == "enter":
		if a.mode == modeEvents {
			idx := a.events.Select()
			if idx >= 0 {
				a.detail.SetEvent(a.events.SelectedEvent())
				a.mode = modeDetail
				a.statusbar.SetViewMode("detail")
			}
		}
		return a, nil

	case msg.String() == "esc":
		switch a.mode {
		case modeDetail:
			a.detail.Close()
			a.events.Deselect()
			a.mode = modeEvents
			a.statusbar.SetViewMode("")
		case modeHelp:
			a.help.Close()
			a.mode = modeEvents
			a.statusbar.SetViewMode("")
		}
		return a, nil

	case msg.String() == "?":
		if a.mode == modeHelp {
			a.help.Close()
			a.mode = modeEvents
		} else {
			a.help.Toggle()
			a.mode = modeHelp
		}
		return a, nil

	case msg.String() == "x":
		a.events.Clear()
		return a, nil

	case msg.String() == "j" || msg.String() == "down":
		if a.mode == modeDetail {
			a.detail.ScrollDown()
		} else {
			a.events.MoveDown()
		}
		return a, nil

	case msg.String() == "k" || msg.String() == "up":
		if a.mode == modeDetail {
			a.detail.ScrollUp()
		} else {
			a.events.MoveUp()
		}
		return a, nil
	}

	return a, nil
}

func (a *App) handleFilterKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.String() {
	case "enter":
		val := a.filterInput.Value()
		switch a.mode {
		case modeFilterEvent:
			a.eventTypeFilter = val
		case modeFilterDistinct:
			a.distinctIDFilter = val
		case modeFilterColumns:
			cols := parsePropColumns(val)
			if a.events.ColumnsExceedWidth(cols) {
				a.warning = "Columns too wide for terminal, not saved"
				a.warningExpiry = time.Now().Add(3 * time.Second)
				a.filterInput.Blur()
				a.mode = modeEvents
				return a, nil
			}
			a.events.SetPropertyColumns(cols)
			a.saveColumnPrefs(cols)
			a.filterInput.Blur()
			a.mode = modeEvents
			return a, nil
		}
		a.filterInput.Blur()
		a.mode = modeEvents
		a.statusbar.SetFilters(a.eventTypeFilter, a.distinctIDFilter)
		a.events.Clear()
		a.geo.Clear()
		a.eventsThisSecond = 0
		a.rateBuckets = nil
		a.stats.SetEventRate(0)

		// Stop old streams and reconnect with new filters
		a.eventsStream.Stop()
		a.geoStream.Stop()
		a.cancel()
		a.ctx, a.cancel = context.WithCancel(context.Background())
		a.client = sse.NewClient(
			a.creds.LivestreamHost,
			a.creds.Token,
			a.eventTypeFilter,
			a.distinctIDFilter,
			a.geoOnly,
		)
		a.eventsStream = sse.NewStream(a.client, false, a.ctx)
		a.geoStream = sse.NewStream(a.client, true, a.ctx)
		return a, a.client.PollStats(a.ctx)

	case "esc":
		a.filterInput.Blur()
		a.mode = modeEvents
		return a, nil
	}

	var cmd tea.Cmd
	a.filterInput, cmd = a.filterInput.Update(msg)
	return a, cmd
}

// parsePropColumns parses a column spec string like:
//
//	$current_url:40,$browser:15,"prop:with:colons":20
//
// Quoted names handle properties containing colons or commas.
// If no width is given, defaults to 20.
func parsePropColumns(input string) []views.PropColumn {
	var cols []views.PropColumn
	remaining := strings.TrimSpace(input)

	for remaining != "" {
		var name string
		var widthStr string

		// Handle quoted name
		if strings.HasPrefix(remaining, `"`) {
			end := strings.Index(remaining[1:], `"`)
			if end == -1 {
				// Unterminated quote, take rest as name
				name = remaining[1:]
				remaining = ""
			} else {
				name = remaining[1 : end+1]
				remaining = remaining[end+2:] // skip closing quote
			}
			// After the closing quote, expect :width or , or end
			remaining = strings.TrimLeft(remaining, " ")
			if strings.HasPrefix(remaining, ":") {
				remaining = remaining[1:]
				commaIdx := strings.Index(remaining, ",")
				if commaIdx == -1 {
					widthStr = strings.TrimSpace(remaining)
					remaining = ""
				} else {
					widthStr = strings.TrimSpace(remaining[:commaIdx])
					remaining = strings.TrimSpace(remaining[commaIdx+1:])
				}
			} else if strings.HasPrefix(remaining, ",") {
				remaining = strings.TrimSpace(remaining[1:])
			}
		} else {
			// Unquoted: split on comma first to get this entry
			commaIdx := strings.Index(remaining, ",")
			var entry string
			if commaIdx == -1 {
				entry = strings.TrimSpace(remaining)
				remaining = ""
			} else {
				entry = strings.TrimSpace(remaining[:commaIdx])
				remaining = strings.TrimSpace(remaining[commaIdx+1:])
			}

			// Split entry on last colon to get name:width
			lastColon := strings.LastIndex(entry, ":")
			if lastColon == -1 {
				name = entry
			} else {
				name = strings.TrimSpace(entry[:lastColon])
				widthStr = strings.TrimSpace(entry[lastColon+1:])
			}
		}

		if name == "" {
			continue
		}

		width := 40
		if widthStr != "" {
			var w int
			if _, err := fmt.Sscanf(widthStr, "%d", &w); err == nil && w > 0 {
				width = w
			}
		}

		cols = append(cols, views.PropColumn{Name: name, Width: width})
	}

	if len(cols) == 0 {
		return []views.PropColumn{{Name: "$current_url", Width: 40}}
	}
	return cols
}

func (a *App) saveColumnPrefs(cols []views.PropColumn) {
	cfg := config.Load()
	cfg.Columns = make([]config.Column, len(cols))
	for i, c := range cols {
		cfg.Columns[i] = config.Column{Name: c.Name, Width: c.Width}
	}
	_ = config.Save(cfg)
}

func (a *App) resize() {
	eventsHeight := a.height - 6
	if eventsHeight < 3 {
		eventsHeight = 3
	}
	debug.Log("resize", "eventsHeight=%d (terminal=%dx%d)", eventsHeight, a.width, a.height)
	a.events.SetSize(a.width, eventsHeight)
	if a.events.ColumnsExceedWidth(a.events.PropertyColumns()) {
		a.events.SetPropertyColumns(nil)
	}
	a.detail.SetSize(a.width, a.height-4)
	a.stats.SetSize(a.width)
	a.geo.SetSize(a.width)
	a.statusbar.SetSize(a.width)
	a.help.SetSize(a.width, a.height)
}

func (a *App) View() string {
	if a.width == 0 || a.height == 0 {
		return ""
	}

	if a.mode == modeHelp && a.help.IsVisible() {
		return a.help.View()
	}

	if a.mode == modeDetail && a.detail.IsVisible() {
		header := a.statusbar.ViewHeader()
		detail := a.detail.View()
		footer := a.statusbar.ViewFooter()
		return lipgloss.JoinVertical(lipgloss.Left, header, detail, footer)
	}

	header := a.statusbar.ViewHeader()
	statsBar := a.stats.View()
	eventsView := a.events.View()
	geoBar := a.geo.View()
	footer := a.statusbar.ViewFooter()

	var overlay string
	if a.mode == modeFilterEvent || a.mode == modeFilterDistinct || a.mode == modeFilterColumns {
		var label string
		switch a.mode {
		case modeFilterDistinct:
			label = "Distinct ID: "
		case modeFilterColumns:
			label = "Columns: "
		default:
			label = "Event filter: "
		}
		inputStyle := lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.AdaptiveColor{Light: "#1D4AFF", Dark: "#1D4AFF"}).
			Padding(0, 1)

		overlay = inputStyle.Width(a.width - 4).Render(label + a.filterInput.View())
	} else if a.warning != "" && time.Now().Before(a.warningExpiry) {
		warnStyle := lipgloss.NewStyle().
			Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
			Background(lipgloss.AdaptiveColor{Light: "#D32F2F", Dark: "#D32F2F"}).
			Bold(true).
			Padding(0, 1).
			Width(a.width)
		overlay = warnStyle.Render(a.warning)
	} else {
		a.warning = ""
	}

	var content string
	if overlay != "" {
		content = lipgloss.JoinVertical(lipgloss.Left, header, statsBar, overlay, eventsView, geoBar, footer)
	} else {
		content = lipgloss.JoinVertical(lipgloss.Left, header, statsBar, eventsView, geoBar, footer)
	}

	return content
}
