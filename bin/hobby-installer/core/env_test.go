package core

import (
	"os"
	"testing"
)

func TestInternalRequestTokenIsDedicatedAndKept(t *testing.T) {
	cases := []struct {
		name      string
		existing  string
		wantToken string
	}{
		{name: "fresh install generates a token"},
		{name: "upgrade adds a missing token", existing: "POSTHOG_SECRET=s3cret\nDOMAIN=example.com\n"},
		{
			name:      "upgrade keeps an existing token",
			existing:  "POSTHOG_SECRET=s3cret\nDOMAIN=example.com\nINTERNAL_REQUEST_TOKEN=keep-me\n",
			wantToken: "keep-me",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Chdir(t.TempDir())

			if tc.existing == "" {
				config, err := NewEnvConfig("example.com", "latest")
				if err != nil {
					t.Fatal(err)
				}
				if err := config.WriteEnvFile(); err != nil {
					t.Fatal(err)
				}
			} else {
				if err := os.WriteFile(".env", []byte(tc.existing), 0600); err != nil {
					t.Fatal(err)
				}
				if err := UpdateEnvForUpgrade(""); err != nil {
					t.Fatal(err)
				}
			}

			token := ReadEnvValue("INTERNAL_REQUEST_TOKEN")
			if tc.wantToken != "" && token != tc.wantToken {
				t.Fatalf("token = %q, want %q", token, tc.wantToken)
			}
			if token == "" || token == ReadEnvValue("POSTHOG_SECRET") {
				t.Fatalf("token = %q, want a value of its own", token)
			}
		})
	}
}
