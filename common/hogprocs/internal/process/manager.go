package process

import (
	"sync"

	bubbletea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/hogprocs/internal/config"
)

// Manager holds and orchestrates all processes for the dev environment.
type Manager struct {
	mu     sync.Mutex
	procs  []*Process
	byName map[string]*Process
	send   func(bubbletea.Msg)
}

// NewManager creates a Manager from a config, building Process objects in stable order.
func NewManager(cfg *config.Config) *Manager {
	names := cfg.OrderedNames()
	procs := make([]*Process, 0, len(names))
	byName := make(map[string]*Process, len(names))

	for _, name := range names {
		proc := NewProcess(name, cfg.Procs[name])
		procs = append(procs, proc)
		byName[name] = proc
	}

	return &Manager{
		procs:  procs,
		byName: byName,
	}
}

// SetSend wires the tea.Program.Send function so process goroutines can deliver messages.
// Must be called before StartAll.
func (m *Manager) SetSend(send func(bubbletea.Msg)) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.send = send
}

// StartAll launches all processes whose autostart is not explicitly false.
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

// StopAll sends SIGTERM to every running process (called on quit).
func (m *Manager) StopAll() {
	m.mu.Lock()
	procs := m.procs
	m.mu.Unlock()
	for _, p := range procs {
		p.Stop()
	}
}

// Procs returns the ordered slice of all processes (safe for reading status/lines).
func (m *Manager) Procs() []*Process {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := make([]*Process, len(m.procs))
	copy(cp, m.procs)
	return cp
}

// Get returns a process by name.
func (m *Manager) Get(name string) (*Process, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.byName[name]
	return p, ok
}

// Send returns the send function so the TUI can pass it to Restart calls.
func (m *Manager) Send() func(bubbletea.Msg) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.send
}
