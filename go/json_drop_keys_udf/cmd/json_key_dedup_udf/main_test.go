package main

import (
	"bytes"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestProcessLineErrorsOnMalformedJSON(t *testing.T) {
	var buf bytes.Buffer
	err := processLine(nil, []byte("{\"a\":"), &buf)
	assert.Error(t, err, "expected error for malformed JSON, got nil")
}

func TestDropKeysJSON(t *testing.T) {
	cases := []struct {
		name, input, want string
		keys              []string
	}{
		{
			"empty",
			"{}",
			"{}",
			nil,
		},
		{
			"empty2",
			"{}",
			"{}",
			[]string{"jeden"},
		},
		{
			"one one key to be dropped",
			`{"jeden": 1}`,
			`{}`,
			[]string{"jeden"},
		},
		{
			name:  "one key to be dropped, one to be kept",
			input: `{"jeden": 1, "dwa": 2}`,
			want:  `{"dwa": 2}`,
			keys:  []string{"jeden"},
		},
		{
			name:  "one key to be dropped one to be kept (order doesnt matter)",
			input: `{"dwa": 2, "jeden": 1}`,
			want:  `{"dwa": 2}`,
			keys:  []string{"jeden"},
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var buf bytes.Buffer
			err := processLine(c.keys, []byte(c.input), &buf)
			assert.NoError(t, err, "unexpected error processing line")
			assert.Equal(t, c.want, buf.String(), "unexpected output")
		})
	}
}

func TestShouldStringifyNumber(t *testing.T) {
	tests := map[string]bool{
		"0":                    false,
		"42":                   false,
		"9223372036854775807":  false,
		"9223372036854775808":  true,
		"-9223372036854775808": false,
		"-9223372036854775809": true,
		"1.25":                 false,
		"1e6":                  false,
	}

	for input, want := range tests {
		if got := shouldStringifyNumber(input); got != want {
			t.Fatalf("shouldStringifyNumber(%q) = %v, want %v", input, got, want)
		}
	}
}
