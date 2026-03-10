package config

import (
	"os"
	"path/filepath"
	"testing"
)

func writeYAML(t *testing.T, content string) string {
	t.Helper()
	f, err := os.CreateTemp(t.TempDir(), "*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString(content); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return f.Name()
}

func TestLoad_defaults(t *testing.T) {
	path := writeYAML(t, "procs:\n  backend:\n    shell: echo hi\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Scrollback != 10_000 {
		t.Errorf("Scrollback: got %d, want 10000", cfg.Scrollback)
	}
	if cfg.MouseScrollSpeed != 3 {
		t.Errorf("MouseScrollSpeed: got %d, want 3", cfg.MouseScrollSpeed)
	}
}

func TestLoad_explicit(t *testing.T) {
	path := writeYAML(t, "scrollback: 500\nmouse_scroll_speed: 7\nprocs:\n  backend:\n    shell: echo hi\n")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Scrollback != 500 {
		t.Errorf("Scrollback: got %d, want 500", cfg.Scrollback)
	}
	if cfg.MouseScrollSpeed != 7 {
		t.Errorf("MouseScrollSpeed: got %d, want 7", cfg.MouseScrollSpeed)
	}
}

func TestLoad_missingFile(t *testing.T) {
	_, err := Load(filepath.Join(t.TempDir(), "nonexistent.yaml"))
	if err == nil {
		t.Error("expected error for missing file, got nil")
	}
}

func TestLoad_invalidYAML(t *testing.T) {
	path := writeYAML(t, ":\t: bad yaml\n")
	_, err := Load(path)
	if err == nil {
		t.Error("expected error for invalid YAML, got nil")
	}
}

func TestOrderedNames(t *testing.T) {
	tests := []struct {
		name  string
		procs []string
		want  []string
	}{
		{
			name:  "info first, rest alphabetical",
			procs: []string{"backend", "info", "frontend", "celery"},
			want:  []string{"info", "backend", "celery", "frontend"},
		},
		{
			name:  "no info, alphabetical",
			procs: []string{"backend", "frontend", "celery"},
			want:  []string{"backend", "celery", "frontend"},
		},
		{
			name:  "only info",
			procs: []string{"info"},
			want:  []string{"info"},
		},
		{
			name:  "empty",
			procs: []string{},
			want:  []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := &Config{Procs: make(map[string]ProcConfig, len(tt.procs))}
			for _, n := range tt.procs {
				cfg.Procs[n] = ProcConfig{}
			}
			got := cfg.OrderedNames()
			if len(got) != len(tt.want) {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
			for i, name := range got {
				if name != tt.want[i] {
					t.Errorf("index %d: got %q, want %q", i, name, tt.want[i])
				}
			}
		})
	}
}

func TestShouldAutostart(t *testing.T) {
	boolPtr := func(b bool) *bool { return &b }
	tests := []struct {
		name      string
		autostart *bool
		want      bool
	}{
		{"nil defaults to true", nil, true},
		{"explicit true", boolPtr(true), true},
		{"explicit false", boolPtr(false), false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			p := ProcConfig{Autostart: tt.autostart}
			if got := p.ShouldAutostart(); got != tt.want {
				t.Errorf("got %v, want %v", got, tt.want)
			}
		})
	}
}
