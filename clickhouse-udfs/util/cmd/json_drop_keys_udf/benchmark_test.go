package main

import (
	"bytes"
	"fmt"
	"strings"
	"testing"
)

func BenchmarkDropWorkloads(b *testing.B) {
	var dotted, wide strings.Builder
	dotted.WriteByte('{')
	wide.WriteByte('{')
	for i := range 256 {
		if i > 0 {
			dotted.WriteByte(',')
			wide.WriteByte(',')
		}
		fmt.Fprintf(&dotted, `"group.key%d":%d`, i, i)
		fmt.Fprintf(&wide, `"key%d":%d`, i, i)
	}
	dotted.WriteByte('}')
	wide.WriteByte('}')
	for name, input := range map[string]string{
		"wide":      wide.String(),
		"dotted":    dotted.String(),
		"discarded": `{"drop":[` + strings.Repeat(`{"text":"example\ntext"},`, 4095) + `{}],"keep":1}`,
		"escaped":   `{"text":"` + strings.Repeat(`text\nwith\tquotes\" and unicode\u263a `, 256) + `"}`,
	} {
		b.Run(name, func(b *testing.B) {
			data := []byte(input)
			keys := makeKeyDict([]string{"drop", "group.key1"})
			var output bytes.Buffer
			b.SetBytes(int64(len(data)))
			b.ReportAllocs()
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				if err := processLine(keys, data, &output); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

func BenchmarkDropFixturePaths(b *testing.B) {
	lines, total := loadBenchmarkLines(b)
	for name, paths := range map[string][]string{
		"missing": {"missing"},
		"nested":  {"commit.record.text"},
		"subtree": {"commit"},
	} {
		b.Run(name, func(b *testing.B) {
			keys := makeKeyDict(paths)
			var output bytes.Buffer
			b.SetBytes(int64(total))
			b.ReportAllocs()
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				for _, line := range lines {
					if err := processLine(keys, line, &output); err != nil {
						b.Fatal(err)
					}
				}
			}
		})
	}
}
