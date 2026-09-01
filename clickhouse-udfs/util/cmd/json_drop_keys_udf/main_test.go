package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
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
		{
			name:  "drop nested key with dot notation",
			input: `{"id":1,"props":{"secret":"xxx","public":"yyy"}}`,
			want:  `{"id":1,"props":{"public":"yyy"}}`,
			keys:  []string{"props.secret"},
		},
		{
			name:  "drop deeply nested key",
			input: `{"a":{"b":{"c":1,"d":2}}}`,
			want:  `{"a":{"b":{"d":2}}}`,
			keys:  []string{"a.b.c"},
		},
		{
			name:  "drop entire nested object",
			input: `{"a":{"b":1},"c":2}`,
			want:  `{"c":2}`,
			keys:  []string{"a"},
		},
		{
			name:  "drop keys from root array objects",
			input: `[{"a":1,"b":2},{"a":3}]`,
			want:  `[{"b":2},{}]`,
			keys:  []string{"a"},
		},
		{
			name:  "drop nested path through array objects",
			input: `{"events":[{"a":1,"b":2},{"a":3}]}`,
			want:  `{"events":[{"b":2},{}]}`,
			keys:  []string{"events.a"},
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

func TestMakeKeyDict(t *testing.T) {
	cases := []struct {
		name string
		keys []string
		want jsonKey
	}{
		{
			name: "nil input",
			keys: nil,
			want: jsonKey{},
		},
		{
			name: "empty input",
			keys: []string{},
			want: jsonKey{},
		},
		{
			name: "single top-level key",
			keys: []string{"a"},
			want: jsonKey{"a": nil},
		},
		{
			name: "multiple top-level keys",
			keys: []string{"a", "b", "c"},
			want: jsonKey{"a": nil, "b": nil, "c": nil},
		},
		{
			name: "single nested key",
			keys: []string{"a.b"},
			want: jsonKey{"a": jsonKey{"b": nil}},
		},
		{
			name: "deeply nested key",
			keys: []string{"a.b.c.d"},
			want: jsonKey{"a": jsonKey{"b": jsonKey{"c": jsonKey{"d": nil}}}},
		},
		{
			name: "mixed top-level and nested keys",
			keys: []string{"x", "a.b"},
			want: jsonKey{"x": nil, "a": jsonKey{"b": nil}},
		},
		{
			name: "multiple nested keys under same parent",
			keys: []string{"a.b", "a.c"},
			want: jsonKey{"a": jsonKey{"b": nil, "c": nil}},
		},
		{
			name: "nested key and parent key both specified",
			keys: []string{"a.b", "a"},
			want: jsonKey{"a": nil},
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := makeKeyDict(c.keys)
			assert.Equal(t, c.want, got)
		})
	}
}

func BenchmarkProcessLine(b *testing.B) {
	input := []byte(`{"id":1,"identity":"abc","properties":{"secret":"drop","public":"keep"},"events":[{"identity":"nested","value":1}],"amount":934504962295726700000}`)
	keys := makeKeyDict([]string{"identity", "properties.secret"})
	var buf bytes.Buffer

	b.ReportAllocs()
	b.SetBytes(int64(len(input)))

	for i := 0; i < b.N; i++ {
		if err := processLine(keys, input, &buf); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkProcessFixture(b *testing.B) {
	lines, totalBytes := loadBenchmarkLines(b)
	keys := makeKeyDict([]string{"identity", "properties.secret"})
	var buf bytes.Buffer

	b.ReportAllocs()
	b.SetBytes(int64(totalBytes))
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		for _, line := range lines {
			if err := processLine(keys, line, &buf); err != nil {
				b.Fatal(err)
			}
		}
	}
}

func loadBenchmarkLines(b *testing.B) ([][]byte, int) {
	b.Helper()

	path := os.Getenv("BENCH_FILE")
	if path == "" {
		return generatedBenchmarkLines()
	} else if !filepath.IsAbs(path) {
		path = filepath.Join("../..", path)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		b.Fatal(err)
	}

	rawLines := bytes.Split(bytes.TrimSpace(data), []byte("\n"))
	lines := make([][]byte, 0, len(rawLines))
	totalBytes := 0
	for _, line := range rawLines {
		line = bytes.TrimSpace(line)
		if len(line) == 0 {
			continue
		}
		lines = append(lines, line)
		totalBytes += len(line)
	}

	if len(lines) == 0 {
		b.Fatalf("benchmark file has no JSON lines: %s", path)
	}

	return lines, totalBytes
}

func generatedBenchmarkLines() ([][]byte, int) {
	lines := make([][]byte, 0, 256)
	totalBytes := 0
	for i := 0; i < 256; i++ {
		line := []byte(fmt.Sprintf(
			`{"id":%d,"identity":"user-%d","properties":{"secret":"s%d","public":"p%d"},"events":[{"identity":"nested-%d","value":%d}],"amount":934504962295726700000}`,
			i,
			i,
			i,
			i,
			i,
			i,
		))
		lines = append(lines, line)
		totalBytes += len(line)
	}

	return lines, totalBytes
}
