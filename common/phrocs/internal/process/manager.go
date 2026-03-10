package process

import (
	"sync"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
)

// Orchestrates all processes for the dev environment
type Manager struct {
	mu     sync.Mutex
	procs  []*Process
	byName map[string]*Process
	send   func(tea.Msg)
}

func NewManager(cfg *config.Config) *Manager {
	names := cfg.OrderedNames()
	procs := make([]*Process, 0, len(names))
	byName := make(map[string]*Process, len(names))

	for _, name := range names {
		proc := NewProcess(name, cfg.Procs[name], cfg.Scrollback)
		procs = append(procs, proc)
		byName[name] = proc
	}

	return &Manager{
		procs:  procs,
		byName: byName,
	}
}

// Must be called before StartAll
func (m *Manager) SetSend(send func(tea.Msg)) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.send = send
}

// Launches all processes whose autostart is not explicitly false
func (m *Manager) StartAll() {
	m.mu.Lock()
	send := m.send
	procs := m.procs
	m.mu.Unlock()

	for _, p := range procs {
		if p.Cfg.ShouldAutostart() {
			_ = p.Start(send)
		}
	}
}

// Sends SIGTERM to every running process (called on quit)
func (m *Manager) StopAll() {
	m.mu.Lock()
	procs := m.procs
	m.mu.Unlock()
	for _, p := range procs {
		p.Stop()
	}
}

// Returns the ordered slice of all processes (safe for reading status/lines)
func (m *Manager) Procs() []*Process {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := make([]*Process, len(m.procs))
	copy(cp, m.procs)
	return cp
}

// Returns a process by name
func (m *Manager) Get(name string) (*Process, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.byName[name]
	return p, ok
}

// Returns the send function so the TUI can pass it to Restart calls
func (m *Manager) Send() func(tea.Msg) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.send
}
