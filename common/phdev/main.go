// phdev is a PostHog-branded dev process runner built with Bubble Tea.
//
// It is a drop-in replacement for mprocs: it reads the same YAML config
// that `hogli dev:generate` produces and renders a customisable TUI with a
// per-process sidebar, scrollable output panes, and hogli-aware keybindings.
//
// Usage:
//
//	phdev <config.yaml>
package main

import (
	"fmt"
	"os"

	bubbletea "github.com/charmbracelet/bubbletea"
	"github.com/posthog/posthog/phdev/internal/config"
	"github.com/posthog/posthog/phdev/internal/process"
	"github.com/posthog/posthog/phdev/internal/tui"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: phdev <config.yaml>")
		os.Exit(1)
	}

	cfg, err := config.Load(os.Args[1])
	if err != nil {
		fmt.Fprintf(os.Stderr, "phdev: load config: %v\n", err)
		os.Exit(1)
	}

	mgr := process.NewManager(cfg)
	m := tui.New(mgr)

	p := bubbletea.NewProgram(
		m,
		bubbletea.WithAltScreen(),
		bubbletea.WithMouseCellMotion(),
	)

	// Wire the send function before starting processes.
	// StartAll is launched in a goroutine so it doesn't block: p.Send() inside
	// Start() will block briefly on the Bubble Tea channel until p.Run() starts
	// its event loop, at which point everything unblocks naturally. Calling
	// StartAll synchronously before p.Run() deadlocks because the main goroutine
	// would be stuck in p.Send() and p.Run() would never be reached.
	mgr.SetSend(p.Send)
	go mgr.StartAll()

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "phdev: %v\n", err)
		os.Exit(1)
	}
}
