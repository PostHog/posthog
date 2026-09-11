package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/valyala/fastjson"
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
			name:  "dotted key in unfiltered sibling stays literal",
			input: `{"keep":{"a.b":1},"items":{"a.b":2,"a.c":3}}`,
			want:  `{"keep":{"a.b":1},"items":{"a":{"c":3}}}`,
			keys:  []string{"items.a.b"},
		},
		{
			name:  "dotted key at root expands even outside filter",
			input: `{"keep.a.b":1,"items.a.b":2,"items.a.c":3}`,
			want:  `{"keep":{"a":{"b":1}},"items":{"a":{"c":3}}}`,
			keys:  []string{"items.a.b"},
		},
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
			name:  "drop parent when it precedes a nested key",
			input: `{"a":{"b":1,"c":2}}`,
			want:  `{}`,
			keys:  []string{"a", "a.b"},
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

func TestDropKeysPreservesDottedScopeAndEncoding(t *testing.T) {
	for _, tc := range []struct {
		input, want string
		keys        []string
	}{
		{`{"a.b":1,"a":{"c":2},"a.d":3}`, `{"a":{"b":1},"a":{"c":2,"d":3}}`, nil},
		{`{"a.b":1,"a":2,"a.c":3}`, `{"a":{},"a":2,"a":{"c":3}}`, []string{"a.b"}},
		{`{"keep":{"a.b":1},"items":[{"a.b":2,"a.c":3}]}`, `{"keep":{"a.b":1},"items":[{"a":{"c":3}}]}`, []string{"items.a.b"}},
		{`{"a":1,"a":2,"b":3}`, `{"b":3}`, []string{"a"}},
		{`[[{"a.b":1,"a.c":2}],null,3]`, `[[{"a":{"c":2}}],null,3]`, []string{"a.b"}},
		{`{"\u0061":1,"text":"\u0000\u001b\u263a\/","number":-1.230e+04}`, `{"text":"\u0000\u001b☺/","number":-1.230e+04}`, []string{"a"}},
	} {
		var output bytes.Buffer
		if err := processLine(makeKeyDict(tc.keys), []byte(tc.input), &output); err != nil {
			t.Fatal(err)
		}
		if output.String() != tc.want {
			t.Fatalf("input %s: got %s, want %s", tc.input, output.String(), tc.want)
		}
	}
}

func TestDropKeysLargeRowsAndMemoryReuse(t *testing.T) {
	for _, size := range []int{31, 4*1024*1024 + 17} {
		row := `{"keep":"` + strings.Repeat("x", size) + `\n\t","drop":1}`
		want := `{"keep":"` + strings.Repeat("x", size) + `\n\t"}`
		for _, ending := range []string{"", "\n", "\r\n"} {
			var output bytes.Buffer
			if err := run(strings.NewReader(row+ending), &output, makeKeyDict([]string{"drop"})); err != nil {
				t.Fatal(err)
			}
			expected := want
			if ending != "" {
				expected += "\n"
			}
			if output.String() != expected {
				t.Fatalf("row size=%d ending=%q changed", size, ending)
			}
		}
	}
	obj := &objectNode{entries: make([]objectEntry, 1, 32)}
	obj.entries[0] = objectEntry{key: "drop", value: (*scalarNode)(fastjson.MustParse(`"secret"`))}
	obj.DropKeys(makeKeyDict([]string{"drop"}))
	recycleNode(obj)
	for _, entry := range obj.entries[:cap(obj.entries)] {
		if entry.key != "" || entry.value != nil {
			t.Fatal("recycled object retains dropped values")
		}
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }
func TestDropKeysStreamErrors(t *testing.T) {
	if err := run(strings.NewReader(`{"drop":[1,]}`), io.Discard, makeKeyDict([]string{"drop"})); err == nil {
		t.Fatal("malformed discarded value accepted")
	}
	if err := run(strings.NewReader(`{}`), failingWriter{}, nil); !errors.Is(err, io.ErrClosedPipe) {
		t.Fatalf("write error lost: %v", err)
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
	benchmarkProcessLines(b, "testdata/benchmarks/small.jsonl", []string{"identity", "properties.secret"})
}

func BenchmarkProcessFixture(b *testing.B) {
	path := os.Getenv("BENCH_FILE")
	if path == "" {
		path = "testdata/benchmarks/events.jsonl"
	} else if !filepath.IsAbs(path) {
		path = filepath.Join("../..", path)
	}

	for _, tc := range []struct {
		name string
		path string
		keys []string
	}{
		{name: "missing", path: path, keys: []string{"missing"}},
		{name: "nested", path: path, keys: []string{"properties.secret"}},
		{name: "subtree", path: path, keys: []string{"properties"}},
		{name: "array", path: path, keys: []string{"events.identity"}},
		{name: "dotted", path: "testdata/benchmarks/dotted.jsonl", keys: []string{"items.a.b"}},
	} {
		b.Run(tc.name, func(b *testing.B) {
			benchmarkProcessLines(b, tc.path, tc.keys)
		})
	}
}

func benchmarkProcessLines(b *testing.B, path string, keyPaths []string) {
	b.Helper()
	lines, totalBytes := loadBenchmarkLines(b, path)
	keys := makeKeyDict(keyPaths)
	var buf bytes.Buffer

	for _, line := range lines {
		if err := processLine(keys, line, &buf); err != nil {
			b.Fatal(err)
		}
	}
	b.ReportAllocs()
	b.SetBytes(int64(totalBytes / len(lines)))
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		if err := processLine(keys, lines[i%len(lines)], &buf); err != nil {
			b.Fatal(err)
		}
	}
}

func loadBenchmarkLines(b *testing.B, path string) ([][]byte, int) {
	b.Helper()

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
