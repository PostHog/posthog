// hogprocs is a PostHog-branded dev process runner built with Bubble Tea.
//
// It is a drop-in replacement for mprocs: it reads the same YAML config
// that `hogli dev:generate` produces and renders a customisable TUI with a
// per-process sidebar, scrollable output panes, and hogli-aware keybindings.
//
// Usage:
//
//	hogprocs [--debug] <config.yaml>
//
// Flags:
//
//	--debug   Write a debug log to /tmp/hogprocs-debug.log (key inputs, proc
//	          selection changes, status transitions, etc.)
package main

import (
	"fmt"
	"log"
	"os"

	bubbletea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/hogprocs/internal/config"
	"github.com/posthog/posthog/hogprocs/internal/process"
	"github.com/posthog/posthog/hogprocs/internal/tui"
)

func main() {
	// Parse args: optional --debug flag followed by the config path.
	var configPath string
	var logger *log.Logger
	args := os.Args[1:]
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch arg {
		case "--config":
			if i+1 < len(args) {
				configPath = args[i+1]
				i++ // skip the next arg since we consumed it
			}
		case "--debug":
			f, err := os.OpenFile("/tmp/hogprocs-debug.log", os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
			if err != nil {
				fmt.Fprintf(os.Stderr, "hogprocs: open debug log: %v\n", err)
				os.Exit(1)
			}
			// f is intentionally not closed — it lives for the duration of the process.
			logger = log.New(f, "", log.LstdFlags|log.Lmicroseconds)
			logger.Println("debug logging started")
		default:
			if configPath == "" {
				configPath = arg
			}
		}
	}

	if configPath == "" {
		fmt.Fprintln(os.Stderr, "usage: hogprocs [--debug] --config <config.yaml>")
		os.Exit(1)
	}

	cfg, err := config.Load(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "hogprocs: load config: %v\n", configPath, err)
		os.Exit(1)
	}

	mgr := process.NewManager(cfg)
	m := tui.New(mgr, logger)

	p := bubbletea.NewProgram(m)

	// Wire the send function before starting processes.
	// StartAll is launched in a goroutine so it doesn't block: p.Send() inside
	// Start() will block briefly on the Bubble Tea channel until p.Run() starts
	// its event loop, at which point everything unblocks naturally. Calling
	// StartAll synchronously before p.Run() deadlocks because the main goroutine
	// would be stuck in p.Send() and p.Run() would never be reached.
	mgr.SetSend(p.Send)
	go mgr.StartAll()

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "hogprocs: %v\n", err)
		os.Exit(1)
	}
}
