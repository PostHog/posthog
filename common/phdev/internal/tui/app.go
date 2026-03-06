// Package tui implements the Bubble Tea TUI for phdev.
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
	"strings"

	"github.com/charmbracelet/bubbles/help"
	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/bubbles/viewport"
	bubbletea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/posthog/posthog/phdev/internal/process"
)

// headerHeight is the number of terminal lines the header occupies.
const headerHeight = 1

// footerHeight is the minimum number of lines for the collapsed help footer.
const footerHeight = 2 // top border + content line

// Model is the root Bubble Tea model for phdev.
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
}

// New creates a Model backed by mgr. Call tea.NewProgram(New(mgr)) to run it.
func New(mgr *process.Manager) Model {
	return Model{
		mgr:      mgr,
		procs:    mgr.Procs(),
		cursor:   0,
		atBottom: true,
		keys:     defaultKeyMap(),
		help:     help.New(),
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
		// Re-fetch the process slice so status icons refresh on the next render.
		m.procs = m.mgr.Procs()

	case bubbletea.KeyMsg:
		switch {
		case key.Matches(msg, m.keys.Quit):
			m.mgr.StopAll()
			return m, bubbletea.Quit

		case key.Matches(msg, m.keys.Help):
			m.showHelp = !m.showHelp
			// Recompute sizes since footer height may change.
			m = m.applySize()

		case key.Matches(msg, m.keys.NextProc):
			if m.cursor < len(m.procs)-1 {
				m.cursor++
				m = m.loadActiveProc()
			}

		case key.Matches(msg, m.keys.PrevProc):
			if m.cursor > 0 {
				m.cursor--
				m = m.loadActiveProc()
			}

		case key.Matches(msg, m.keys.GotoTop):
			m.viewport.GotoTop()
			m.atBottom = false

		case key.Matches(msg, m.keys.GotoBottom):
			m.viewport.GotoBottom()
			m.atBottom = true

		case key.Matches(msg, m.keys.Restart):
			if p := m.activeProc(); p != nil {
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
func (m Model) View() string {
	if !m.ready {
		return "\n  Initialising...\n"
	}
	return lipgloss.JoinVertical(
		lipgloss.Left,
		m.renderHeader(),
		lipgloss.JoinHorizontal(
			lipgloss.Top,
			m.renderSidebar(),
			m.renderOutput(),
		),
		m.renderFooter(),
	)
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
		m.viewport = viewport.New(vpW, contentH)
		m.ready = true
		m = m.loadActiveProc()
	} else {
		m.viewport.Width = vpW
		m.viewport.Height = contentH
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

	innerW := sidebarWidth - 1 // subtract the right border
	var sb strings.Builder
	for i, p := range m.procs {
		icon := statusIcon(p.Status())
		// Truncate name to leave room for "icon + space" prefix (3 chars).
		name := truncate(p.Name, innerW-3)
		line := fmt.Sprintf("%s %s", icon, name)

		var style lipgloss.Style
		if i == m.cursor {
			style = procActiveStyle.Width(innerW)
		} else {
			style = procInactiveStyle.Width(innerW)
		}
		sb.WriteString(style.Render(line))
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

func statusIcon(s process.Status) string {
	switch s {
	case process.StatusRunning:
		return iconRunning
	case process.StatusPending:
		return iconPending
	case process.StatusStopped:
		return iconStopped
	case process.StatusDone:
		return iconDone
	case process.StatusCrashed:
		return iconCrashed
	default:
		return iconPending
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
