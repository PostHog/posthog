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
			want:  `{"dwa":2}`,
			keys:  []string{"jeden"},
		},
		{
			name:  "one key to be dropped one to be kept (order doesnt matter)",
			input: `{"dwa": 2, "jeden": 1}`,
			want:  `{"dwa":2}`,
			keys:  []string{"jeden"},
		},
		{
			name:  "multiple keys to be dropped one to be kept (order doesnt matter)",
			input: `{"dwa": 2, "jeden": 1, "trzy": 3, "cztery": 4, "piec": {"dwa": 1}}`,
			want:  `{"jeden":1,"cztery":4,"piec":{"dwa":1}}`,
			keys:  []string{"dwa", "trzy"},
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var buf bytes.Buffer
			err := processLine(makeKeyDict(c.keys), []byte(c.input), &buf)
			assert.NoError(t, err, "unexpected error processing line")
			assert.Equal(t, c.want, buf.String(), "unexpected output")
		})
	}
}

func TestParseSingleQuotedArray(t *testing.T) {
	cases := []struct {
		name    string
		input   string
		want    []string
		wantErr bool
	}{
		{"empty array", "[]", nil, false},
		{"single element", "['foo']", []string{"foo"}, false},
		{"two elements", "['foo', 'bar']", []string{"foo", "bar"}, false},
		{"escaped single quote", `['some other \'string']`, []string{"some other 'string"}, false},
		{"mixed", `['some string', 'some other \'string']`, []string{"some string", "some other 'string"}, false},
		{"with spaces", "[ 'a' , 'b' ]", []string{"a", "b"}, false},
		{"no brackets", "foo", nil, true},
		{"unterminated string", "['foo", nil, true},
		{"missing quote", "[foo]", nil, true},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := parseSingleQuotedArray(c.input)
			if c.wantErr {
				assert.Error(t, err)
			} else {
				assert.NoError(t, err)
				assert.Equal(t, c.want, got)
			}
		})
	}
}
