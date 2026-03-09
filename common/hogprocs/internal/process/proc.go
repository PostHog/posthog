package process

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"

	tea "charm.land/bubbletea/v2"
	"github.com/creack/pty"
	"github.com/posthog/posthog/hogprocs/internal/config"
)

// Status represents the lifecycle state of a process.
type Status int

const (
	StatusPending Status = iota
	StatusRunning
	StatusStopped
	StatusDone
	StatusCrashed
)

// String returns a short human-readable label.
func (s Status) String() string {
	switch s {
	case StatusPending:
		return "pending"
	case StatusRunning:
		return "running"
	case StatusStopped:
		return "stopped"
	case StatusDone:
		return "done"
	case StatusCrashed:
		return "crashed"
	default:
		return "unknown"
	}
}

const maxLines = 10_000

// StatusMsg is sent by process goroutines when a process changes state.
type StatusMsg struct {
	Name   string
	Status Status
}

// OutputMsg is sent by process goroutines when a new output line arrives.
type OutputMsg struct {
	Name string
	Line string
}

// Process represents a single managed subprocess.
type Process struct {
	Name string
	Cfg  config.ProcConfig

	mu     sync.Mutex
	status Status
	lines  []string
	cmd    *exec.Cmd
	ptmx   *os.File // pty master; nil when using pipes
}

// NewProcess creates a new Process (not yet started).
func NewProcess(name string, cfg config.ProcConfig) *Process {
	return &Process{
		Name:   name,
		Cfg:    cfg,
		status: StatusPending,
	}
}

// Status returns the current lifecycle status (thread-safe).
func (p *Process) Status() Status {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.status
}

// Lines returns a copy of the accumulated output lines (thread-safe).
func (p *Process) Lines() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	cp := make([]string, len(p.lines))
	copy(cp, p.lines)
	return cp
}

// Start spawns the process. send delivers messages back to the Bubble Tea program.
// It is safe to call Start concurrently; a running process is a no-op.
func (p *Process) Start(send func(tea.Msg)) error {
	p.mu.Lock()
	if p.status == StatusRunning {
		p.mu.Unlock()
		return nil
	}
	p.status = StatusPending
	p.lines = nil
	p.mu.Unlock()

	env := os.Environ()
	for k, v := range p.Cfg.Env {
		env = append(env, fmt.Sprintf("%s=%s", k, v))
	}

	cmd := exec.Command("bash", "-c", p.Cfg.Shell)
	cmd.Env = env

	ptmx, err := pty.Start(cmd)
	if err != nil {
		// Fallback: use combined stdout/stderr pipe when PTY allocation fails (e.g., CI).
		return p.startWithPipe(cmd, send)
	}

	p.mu.Lock()
	p.cmd = cmd
	p.ptmx = ptmx
	p.status = StatusRunning
	p.mu.Unlock()

	send(StatusMsg{Name: p.Name, Status: StatusRunning})

	readDone := make(chan struct{})
	go func() {
		p.readLoop(ptmx, send)
		close(readDone)
	}()

	go func() {
		exitErr := cmd.Wait()

		// Close the pty master to unblock readLoop if still reading.
		p.mu.Lock()
		if p.ptmx != nil {
			p.ptmx.Close()
			p.ptmx = nil
		}
		p.mu.Unlock()

		// Wait for readLoop to drain all buffered output before updating status.
		<-readDone

		st := StatusDone
		if exitErr != nil {
			st = StatusCrashed
		}
		p.mu.Lock()
		// Don't overwrite an explicit Stop() call.
		if p.status != StatusStopped {
			p.status = st
		}
		finalStatus := p.status
		p.mu.Unlock()

		send(StatusMsg{Name: p.Name, Status: finalStatus})

		if p.Cfg.Autorestart && st == StatusCrashed {
			_ = p.Start(send)
		}
	}()

	return nil
}

// startWithPipe falls back to stdout/stderr pipes when PTY allocation fails.
func (p *Process) startWithPipe(cmd *exec.Cmd, send func(tea.Msg)) error {
	pr, pw, err := os.Pipe()
	if err != nil {
		return err
	}
	cmd.Stdout = pw
	cmd.Stderr = pw

	if err := cmd.Start(); err != nil {
		pr.Close()
		pw.Close()
		p.mu.Lock()
		p.status = StatusCrashed
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusCrashed})
		return err
	}

	p.mu.Lock()
	p.cmd = cmd
	p.status = StatusRunning
	p.mu.Unlock()
	send(StatusMsg{Name: p.Name, Status: StatusRunning})

	readDone := make(chan struct{})
	go func() {
		p.readLoop(pr, send)
		close(readDone)
	}()

	go func() {
		exitErr := cmd.Wait()
		// Close the write end so readLoop sees EOF.
		pw.Close()

		<-readDone
		pr.Close()

		st := StatusDone
		if exitErr != nil {
			st = StatusCrashed
		}
		p.mu.Lock()
		if p.status != StatusStopped {
			p.status = st
		}
		finalStatus := p.status
		p.mu.Unlock()

		send(StatusMsg{Name: p.Name, Status: finalStatus})

		if p.Cfg.Autorestart && st == StatusCrashed {
			_ = p.Start(send)
		}
	}()

	return nil
}

// readLoop scans r line by line, appending to the output buffer and sending OutputMsgs.
func (p *Process) readLoop(r io.Reader, send func(tea.Msg)) {
	// Larger buffer to handle long lines (e.g., minified JS error traces).
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 256*1024), 256*1024)

	for scanner.Scan() {
		// PTY output uses \r\n line endings. bufio.Scanner strips \n but
		// leaves the \r, which causes carriage-return to overwrite the start
		// of the line when rendered in the viewport — making all output appear
		// blank. Strip it here so the viewport receives clean lines.
		line := strings.TrimRight(scanner.Text(), "\r")
		p.mu.Lock()
		if len(p.lines) >= maxLines {
			// Discard oldest line to keep the buffer bounded.
			p.lines = p.lines[1:]
		}
		p.lines = append(p.lines, line)
		p.mu.Unlock()
		send(OutputMsg{Name: p.Name, Line: line})
	}
}

// Stop sends SIGTERM to the process and marks it as stopped.
func (p *Process) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cmd != nil && p.cmd.Process != nil {
		_ = p.cmd.Process.Signal(syscall.SIGTERM)
	}
	if p.ptmx != nil {
		p.ptmx.Close()
		p.ptmx = nil
	}
	p.status = StatusStopped
}

// Restart stops the process, clears its output buffer, and starts it again.
func (p *Process) Restart(send func(tea.Msg)) {
	p.Stop()
	_ = p.Start(send)
}

// Resize updates the pty window size to keep output correctly reflowed.
func (p *Process) Resize(cols, rows uint16) {
	p.mu.Lock()
	ptmx := p.ptmx
	p.mu.Unlock()
	if ptmx != nil {
		_ = pty.Setsize(ptmx, &pty.Winsize{Rows: rows, Cols: cols})
	}
}
