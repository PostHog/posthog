package core

import (
	"os"
	"testing"
)

func TestDedicatedSecretsAreGeneratedAndKept(t *testing.T) {
	for _, key := range []string{"INTERNAL_REQUEST_TOKEN", "BROWSERLESS_SECRET"} {
		cases := []struct {
			name      string
			existing  string
			wantValue string
		}{
			{name: "fresh install generates it"},
			{name: "upgrade adds it when missing", existing: "POSTHOG_SECRET=s3cret\nDOMAIN=example.com\n"},
			{
				name:      "upgrade keeps an existing value",
				existing:  "POSTHOG_SECRET=s3cret\nDOMAIN=example.com\n" + key + "=keep-me\n",
				wantValue: "keep-me",
			},
		}

		for _, tc := range cases {
			t.Run(key+"/"+tc.name, func(t *testing.T) {
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

				value := ReadEnvValue(key)
				if tc.wantValue != "" && value != tc.wantValue {
					t.Fatalf("%s = %q, want %q", key, value, tc.wantValue)
				}
				if value == "" || value == ReadEnvValue("POSTHOG_SECRET") {
					t.Fatalf("%s = %q, want a value of its own", key, value)
				}
			})
		}
	}
}
