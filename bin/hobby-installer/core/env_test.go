package core

import (
	"os"
	"strings"
	"testing"
)

func TestUpdateEnvForUpgradeCaddyKeys(t *testing.T) {
	tests := []struct {
		name    string
		env     string
		want    []string
		notWant []string
	}{
		{
			name: "backfills caddy keys from domain and tls block",
			env:  "DOMAIN=posthog.example.com\nTLS_BLOCK=\"acme_ca https://acme.example.com/directory\"\n",
			want: []string{
				`CADDY_HOST="posthog.example.com, http://, https://"`,
				`CADDY_TLS_BLOCK="acme_ca https://acme.example.com/directory"`,
			},
		},
		{
			name:    "keeps existing caddy host",
			env:     "DOMAIN=posthog.example.com\nCADDY_HOST=\"custom.example.com\"\n",
			want:    []string{`CADDY_HOST="custom.example.com"`},
			notWant: []string{"posthog.example.com, http://"},
		},
		{
			name: "replaces blank caddy keys",
			env:  "DOMAIN=posthog.example.com\nTLS_BLOCK=internal\nCADDY_HOST=\nCADDY_TLS_BLOCK=\"\"\n",
			want: []string{
				`CADDY_HOST="posthog.example.com, http://, https://"`,
				`CADDY_TLS_BLOCK="internal"`,
			},
			notWant: []string{"CADDY_HOST=\n", "CADDY_TLS_BLOCK=\"\"\n"},
		},
		{
			name: "replaces quoted empty caddy host without trailing newline",
			env:  "DOMAIN=posthog.example.com\nCADDY_HOST=''",
			want: []string{`CADDY_HOST="posthog.example.com, http://, https://"`},
		},
		{
			name: "replaces the effective blank duplicate",
			env:  "DOMAIN=posthog.example.com\nCADDY_HOST=custom.example.com\nCADDY_HOST=\n",
			want: []string{`CADDY_HOST="posthog.example.com, http://, https://"`},
		},
		{
			name: "keeps the effective custom duplicate",
			env:  "DOMAIN=posthog.example.com\nCADDY_HOST=\nCADDY_HOST=custom.example.com\n",
			want: []string{`CADDY_HOST=custom.example.com`},
		},
		{
			name:    "skips caddy keys without domain or tls block",
			env:     "TLS_BLOCK=\n",
			notWant: []string{"CADDY_HOST=", "CADDY_TLS_BLOCK="},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Chdir(t.TempDir())
			if err := os.WriteFile(".env", []byte(tt.env), 0600); err != nil {
				t.Fatal(err)
			}

			if err := UpdateEnvForUpgrade(""); err != nil {
				t.Fatal(err)
			}
			firstData, err := os.ReadFile(".env")
			if err != nil {
				t.Fatal(err)
			}
			if err := UpdateEnvForUpgrade(""); err != nil {
				t.Fatal(err)
			}

			data, err := os.ReadFile(".env")
			if err != nil {
				t.Fatal(err)
			}
			got := string(data)
			if got != string(firstData) {
				t.Errorf("expected second upgrade to keep .env unchanged, got:\n%s", got)
			}
			for _, w := range tt.want {
				if !strings.Contains(got, w+"\n") {
					t.Errorf("expected .env to contain %q, got:\n%s", w, got)
				}
				parts := strings.SplitN(w, "=", 2)
				if actual := ReadEnvValue(parts[0]); actual != strings.Trim(parts[1], "\"'") {
					t.Errorf("expected effective %s value %q, got %q", parts[0], parts[1], actual)
				}
			}
			for _, nw := range tt.notWant {
				if strings.Contains(got, nw) {
					t.Errorf("expected .env not to contain %q, got:\n%s", nw, got)
				}
			}
		})
	}
}
