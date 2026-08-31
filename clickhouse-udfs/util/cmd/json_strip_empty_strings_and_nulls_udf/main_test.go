package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestProcessLine(t *testing.T) {
	tests := map[string]string{
		`{"empty":"","null":null,"object":{"nested":null},"array":[null,"",{},[]]}`:                                            `null`,
		`{"keep":0,"false":false,"text":" ","nested":{"drop":null,"keep":"x"},"array":[null,"",{},[],{"drop":null,"keep":1}]}`: `{"keep":0,"false":false,"text":" ","nested":{"keep":"x"},"array":[{"keep":1}]}`,
		`{"a":1,"a":null,"a":2}`:      `{"a":1,"a":2}`,
		`[null,"",[],{},0,false,"x"]`: `[0,false,"x"]`,
		`934504962295726700000`:       `"934504962295726700000"`,
	}

	for input, want := range tests {
		var buf bytes.Buffer
		if err := processLine([]byte(input), &buf); err != nil {
			t.Fatalf("processLine(%s) returned error: %v", input, err)
		}
		if got := buf.String(); got != want {
			t.Fatalf("processLine(%s) = %s, want %s", input, got, want)
		}
	}
}

func TestRunMultipleChunks(t *testing.T) {
	var output bytes.Buffer
	if err := run(strings.NewReader("{\"a\":null}\n{\"a\":1}\n"), &output); err != nil {
		t.Fatal(err)
	}
	if got, want := output.String(), "null\n{\"a\":1}\n"; got != want {
		t.Fatalf("run output = %q, want %q", got, want)
	}
}

func TestRunChunked(t *testing.T) {
	var output bytes.Buffer
	input := "2\n{\"a\":null}\n{\"a\":1}\n1\n[null,2]\n"
	if err := runChunked(strings.NewReader(input), &output); err != nil {
		t.Fatal(err)
	}
	if got, want := output.String(), "null\n{\"a\":1}\n[2]\n"; got != want {
		t.Fatalf("runChunked output = %q, want %q", got, want)
	}
}

func TestMalformedJSONFails(t *testing.T) {
	var buf bytes.Buffer
	if err := processLine([]byte(`{"a":`), &buf); err == nil {
		t.Fatal("expected malformed JSON to fail")
	}
}

func BenchmarkProcessLine(b *testing.B) {
	input := []byte(`{"empty":"","null":null,"nested":{"empty":"","value":"x"},"arr":[null,"",{},[],{"value":1}],"amount":934504962295726700000}`)
	var buf bytes.Buffer
	b.ReportAllocs()
	b.SetBytes(int64(len(input)))
	for i := 0; i < b.N; i++ {
		if err := processLine(input, &buf); err != nil {
			b.Fatal(err)
		}
	}
}
