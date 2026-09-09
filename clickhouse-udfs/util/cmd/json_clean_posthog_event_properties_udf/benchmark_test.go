package main

import (
	"bytes"
	"fmt"
	"io"
	"strings"
	"testing"
)

func BenchmarkProcessWorkloads(b *testing.B) {
	var wide, dotted strings.Builder
	wide.WriteByte('{')
	dotted.WriteByte('{')
	for i := range 256 {
		if i > 0 {
			wide.WriteByte(',')
			dotted.WriteByte(',')
		}
		fmt.Fprintf(&wide, `"key%d":%d`, i, i)
		fmt.Fprintf(&dotted, `"group.key%d":%d`, i, i)
	}
	wide.WriteByte('}')
	dotted.WriteByte('}')
	for name, input := range map[string]string{
		"clean":        `{"event":"pageview","properties":{"path":"/docs","duration":123,"active":true}}`,
		"wide":         wide.String(),
		"dotted":       dotted.String(),
		"escaped":      `{"text":"` + strings.Repeat(`text\nwith\tquotes\" and unicode\u263a `, 256) + `"}`,
		"dropped":      `{"$ai_input":[` + strings.Repeat(`{"role":"user","content":"example\ntext"},`, 4095) + `{}],"keep":1}`,
		"temporary":    `{"$set":` + wide.String() + `,"keep":1}`,
		"featureFlags": `{"$feature/z":true,"$feature/a":"test","$feature/m":false,"$exception_list":"{\"type\":\"Error\"}"}`,
	} {
		b.Run(name, func(b *testing.B) {
			data := []byte(input)
			var proc processor
			var output bytes.Buffer
			b.SetBytes(int64(len(data)))
			b.ReportAllocs()
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				if err := proc.processLine(data, &output); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

func BenchmarkRunFixture(b *testing.B) {
	lines, _ := loadBenchmarkLines(b)
	var input bytes.Buffer
	for start := 0; start < len(lines); start += 1024 {
		chunk := lines[start:min(start+1024, len(lines))]
		fmt.Fprintln(&input, len(chunk))
		for _, line := range chunk {
			input.Write(line)
			input.WriteByte('\n')
		}
	}
	for _, kind := range []propertiesKind{eventProperties, personProperties, temporaryProperties} {
		b.Run(fmt.Sprint(kind), func(b *testing.B) {
			b.SetBytes(int64(input.Len()))
			b.ReportAllocs()
			for i := 0; i < b.N; i++ {
				if err := runChunked(bytes.NewReader(input.Bytes()), io.Discard, kind); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}
