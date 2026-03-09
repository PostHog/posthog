// Package tui implements the Bubble Tea TUI for hogprocs.
//
// Layout:
//
//	┌──────────────────────────────────────────┐
//	│  PostHog Dev          ● N running        │  ← header
//	├────────────────┬─────────────────────────┤
//	│ ● backend      │ (process output)         │
//	│ ● frontend     │                          │  ← sidebar + viewport
//	│ ✗ capture      │                          │
//	├────────────────┴─────────────────────────┤
//	│ j next  k prev  r restart  q quit  ? help │  ← footer
//	└──────────────────────────────────────────┘
package tui

import (
	"fmt"
	"image/color"
	"log"
	"strings"

	bubbletea "charm.land/bubbletea/v2"
	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/viewport"
	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/hogprocs/internal/process"
)

// headerHeight is the number of terminal lines the header occupies.
const headerHeight = 1

// footerHeight is the minimum number of lines for the collapsed help footer.
const footerHeight = 2 // top border + content line

// Model is the root Bubble Tea model for hogprocs.
type Model struct {
	mgr   *process.Manager
	procs []*process.Process

	// cursor is the index of the currently selected process in the sidebar.
	cursor int

	viewport viewport.Model
	// atBottom tracks whether the viewport is auto-scrolling to the tail of output.
	atBottom bool

	keys     keyMap
	help     help.Model
	showHelp bool

	width  int
	height int
	ready  bool

	// log is non-nil when --debug is active; writes go to /tmp/hogprocs-debug.log.
	log *log.Logger
}

// New creates a Model backed by mgr. Call tea.NewProgram(New(mgr, nil)) to run it.
// Pass a non-nil logger to enable debug logging (key inputs, selection changes, etc.).
func New(mgr *process.Manager, logger *log.Logger) Model {
	return Model{
		mgr:      mgr,
		procs:    mgr.Procs(),
		cursor:   0,
		atBottom: true,
		keys:     defaultKeyMap(),
		help:     help.New(),
		log:      logger,
	}
}

// dbg writes a formatted debug message when debug logging is active.
func (m Model) dbg(format string, args ...any) {
	if m.log != nil {
		m.log.Printf(format, args...)
	}
}

// Init satisfies tea.Model. Processes are started externally before p.Run().
func (m Model) Init() bubbletea.Cmd {
	return nil
}

// Update handles all incoming Bubble Tea messages.
func (m Model) Update(msg bubbletea.Msg) (bubbletea.Model, bubbletea.Cmd) {
	var cmds []bubbletea.Cmd

	switch msg := msg.(type) {

	case bubbletea.WindowSizeMsg:
		m.dbg("resize: %dx%d", msg.Width, msg.Height)
		m.width = msg.Width
		m.height = msg.Height
		m = m.applySize()

	case process.OutputMsg:
		// Rebuild viewport content only for the active process to keep rendering cheap.
		if m.ready && m.activeProc() != nil && m.activeProc().Name == msg.Name {
			m.viewport.SetContent(m.buildContent())
			if m.atBottom {
				m.viewport.GotoBottom()
			}
		}

	case process.StatusMsg:
		m.dbg("status: proc=%s status=%s", msg.Name, msg.Status)
		// Re-fetch the process slice so status icons refresh on the next render.
		m.procs = m.mgr.Procs()

	case bubbletea.KeyPressMsg:
		m.dbg("key: %q", msg.String())
		switch {
		case key.Matches(msg, m.keys.Quit):
			m.mgr.StopAll()
			return m, bubbletea.Quit

		case key.Matches(msg, m.keys.Help):
			m.showHelp = !m.showHelp
			m.dbg("help toggled: showHelp=%v", m.showHelp)
			// Recompute sizes since footer height may change.
			m = m.applySize()

		case key.Matches(msg, m.keys.NextProc):
			if m.cursor < len(m.procs)-1 {
				prev := m.cursor
				m.cursor++
				m.dbg("proc selected: %d→%d (%s)", prev, m.cursor, m.procs[m.cursor].Name)
				m = m.loadActiveProc()
			}

		case key.Matches(msg, m.keys.PrevProc):
			if m.cursor > 0 {
				prev := m.cursor
				m.cursor--
				m.dbg("proc selected: %d→%d (%s)", prev, m.cursor, m.procs[m.cursor].Name)
				m = m.loadActiveProc()
			}

		case key.Matches(msg, m.keys.GotoTop):
			m.dbg("viewport: goto top")
			m.viewport.GotoTop()
			m.atBottom = false

		case key.Matches(msg, m.keys.GotoBottom):
			m.dbg("viewport: goto bottom")
			m.viewport.GotoBottom()
			m.atBottom = true

		case key.Matches(msg, m.keys.Restart):
			if p := m.activeProc(); p != nil {
				m.dbg("restart: proc=%s", p.Name)
				send := m.mgr.Send()
				go p.Restart(send)
			}

		default:
			// Forward remaining key events to the viewport for scrolling.
			var vpCmd bubbletea.Cmd
			m.viewport, vpCmd = m.viewport.Update(msg)
			cmds = append(cmds, vpCmd)
			m.atBottom = m.viewport.AtBottom()
		}

	case bubbletea.MouseMsg:
		var vpCmd bubbletea.Cmd
		m.viewport, vpCmd = m.viewport.Update(msg)
		cmds = append(cmds, vpCmd)
		m.atBottom = m.viewport.AtBottom()
	}

	return m, bubbletea.Batch(cmds...)
}

// View renders the full TUI as a single string.
func (m Model) View() bubbletea.View {
	if !m.ready {
		v := bubbletea.NewView("\n  Initialising...\n")
		v.AltScreen = true
		v.MouseMode = bubbletea.MouseModeCellMotion
		return v
	}
	v := bubbletea.NewView(lipgloss.JoinVertical(
		lipgloss.Left,
		m.renderHeader(),
		lipgloss.JoinHorizontal(
			lipgloss.Top,
			m.renderSidebar(),
			m.renderOutput(),
		),
		m.renderFooter(),
	))
	v.AltScreen = true
	v.MouseMode = bubbletea.MouseModeCellMotion
	return v
}

// ── helpers ──────────────────────────────────────────────────────────────────

func (m Model) activeProc() *process.Process {
	if len(m.procs) == 0 || m.cursor >= len(m.procs) {
		return nil
	}
	return m.procs[m.cursor]
}

// applySize recalculates viewport/sidebar dimensions whenever the terminal resizes
// or the footer height changes.
func (m Model) applySize() Model {
	fh := footerHeight
	if m.showHelp {
		fh = 7
	}
	contentH := m.height - headerHeight - fh
	if contentH < 1 {
		contentH = 1
	}
	// sidebarWidth includes the right border character, so subtract 1 for the
	// border and 1 for the padding inside the viewport.
	vpW := m.width - sidebarWidth
	if vpW < 1 {
		vpW = 1
	}

	if !m.ready {
		m.viewport = viewport.New(viewport.WithWidth(vpW), viewport.WithHeight(contentH))
		m.ready = true
		m = m.loadActiveProc()
	} else {
		m.viewport.SetWidth(vpW)
		m.viewport.SetHeight(contentH)
	}

	// Keep every pty window size in sync with the output pane so programs
	// that detect terminal width (webpack, Django dev-server) reflow correctly.
	for _, p := range m.procs {
		p.Resize(uint16(vpW), uint16(contentH))
	}

	return m
}

// loadActiveProc reloads the viewport with the selected process's output.
func (m Model) loadActiveProc() Model {
	if !m.ready {
		return m
	}
	m.viewport.SetContent(m.buildContent())
	if m.atBottom {
		m.viewport.GotoBottom()
	}
	return m
}

// buildContent joins the active process's output lines into a viewport content string.
func (m Model) buildContent() string {
	p := m.activeProc()
	if p == nil {
		return ""
	}
	return strings.Join(p.Lines(), "\n")
}

// ── renderers ─────────────────────────────────────────────────────────────────

func (m Model) renderHeader() string {
	brand := headerBrandStyle.Render("  PostHog Dev")

	running := 0
	for _, p := range m.procs {
		if p.Status() == process.StatusRunning {
			running++
		}
	}
	meta := headerMetaStyle.Render(fmt.Sprintf("%d running  ", running))

	gap := m.width - lipgloss.Width(brand) - lipgloss.Width(meta)
	if gap < 0 {
		gap = 0
	}
	spacer := headerMetaStyle.Width(gap).Render("")
	return lipgloss.JoinHorizontal(lipgloss.Top, brand, spacer, meta)
}

func (m Model) renderSidebar() string {
	fh := footerHeight
	if m.showHelp {
		fh = 7
	}
	h := m.height - headerHeight - fh
	if h < 1 {
		h = 1
	}

	// innerW is the usable column width inside the border.
	innerW := sidebarWidth - 1

	var sb strings.Builder
	for i, p := range m.procs {
		iconChar := statusIconChar(p.Status())
		iconColor := statusIconColor(p.Status())

		// Reserve 3 visible chars for left-padding (1) + icon (1) + space (1).
		name := truncate(p.Name, innerW-3)

		// Render icon and name as *separate* lipgloss segments that share the
		// same background colour.  This avoids embedding pre-rendered ANSI
		// strings (which carry their own \033[m reset) inside an outer style,
		// which would silently terminate the background highlight after the icon
		// and make the active-row cursor invisible.
		if i == m.cursor {
			base := lipgloss.NewStyle().Background(colorDarkGrey).Bold(true)
			iconSeg := base.Copy().PaddingLeft(1).Foreground(iconColor).Render(iconChar)
			// Width covers the remaining columns: innerW minus the 2 chars
			// already consumed by PaddingLeft + icon.
			nameSeg := base.Copy().Foreground(colorWhite).Width(innerW - 2).Render(" " + name)
			sb.WriteString(iconSeg + nameSeg)
		} else {
			iconSeg := lipgloss.NewStyle().PaddingLeft(1).Foreground(iconColor).Render(iconChar)
			nameSeg := lipgloss.NewStyle().Foreground(colorGrey).Width(innerW - 2).Render(" " + name)
			sb.WriteString(iconSeg + nameSeg)
		}
		sb.WriteByte('\n')
	}

	// Pad remaining rows so the sidebar border extends the full height.
	for i := len(m.procs); i < h; i++ {
		sb.WriteString(procInactiveStyle.Width(innerW).Render(""))
		sb.WriteByte('\n')
	}

	return sidebarBorderStyle.Height(h).Render(sb.String())
}

func (m Model) renderOutput() string {
	return m.viewport.View()
}

func (m Model) renderFooter() string {
	var content string
	if m.showHelp {
		content = m.help.FullHelpView(m.keys.FullHelp())
	} else {
		content = m.help.ShortHelpView(m.keys.ShortHelp())
	}
	return footerStyle.Width(m.width - 2).Render(content)
}

// ── utility ───────────────────────────────────────────────────────────────────

// statusIconChar returns the plain Unicode character for the given status.
func statusIconChar(s process.Status) string {
	switch s {
	case process.StatusRunning:
		return iconCharRunning
	case process.StatusPending:
		return iconCharPending
	case process.StatusStopped:
		return iconCharStopped
	case process.StatusDone:
		return iconCharDone
	case process.StatusCrashed:
		return iconCharCrashed
	default:
		return iconCharPending
	}
}

// statusIconColor returns the lipgloss colour associated with the given status.
func statusIconColor(s process.Status) color.Color {
	switch s {
	case process.StatusRunning:
		return colorGreen
	case process.StatusPending:
		return colorYellow
	case process.StatusStopped, process.StatusDone:
		return colorGrey
	case process.StatusCrashed:
		return colorRed
	default:
		return colorYellow
	}
}

func truncate(s string, maxLen int) string {
	if maxLen <= 0 {
		return ""
	}
	runes := []rune(s)
	if len(runes) <= maxLen {
		return s
	}
	return string(runes[:maxLen-1]) + "…"
}
