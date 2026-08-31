package main

import (
	"bufio"
	"bytes"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"

	"github.com/valyala/fastjson"
)

type processor struct {
	parser fastjson.Parser
}

func appendCleanJSON(dst []byte, value *fastjson.Value) ([]byte, bool) {
	start := len(dst)
	switch value.Type() {
	case fastjson.TypeNull:
		return dst, false
	case fastjson.TypeString:
		if len(value.GetStringBytes()) == 0 {
			return dst, false
		}
		return value.MarshalTo(dst), true
	case fastjson.TypeObject:
		obj, _ := value.Object()
		dst = append(dst, '{')
		kept := 0
		obj.Visit(func(key []byte, child *fastjson.Value) {
			entryStart := len(dst)
			if kept > 0 {
				dst = append(dst, ',')
			}
			dst = strconv.AppendQuote(dst, string(key))
			dst = append(dst, ':')
			var keep bool
			dst, keep = appendCleanJSON(dst, child)
			if keep {
				kept++
			} else {
				dst = dst[:entryStart]
			}
		})
		if kept == 0 {
			return dst[:start], false
		}
		return append(dst, '}'), true
	case fastjson.TypeArray:
		values, _ := value.Array()
		dst = append(dst, '[')
		kept := 0
		for _, child := range values {
			itemStart := len(dst)
			if kept > 0 {
				dst = append(dst, ',')
			}
			var keep bool
			dst, keep = appendCleanJSON(dst, child)
			if keep {
				kept++
			} else {
				dst = dst[:itemStart]
			}
		}
		if kept == 0 {
			return dst[:start], false
		}
		return append(dst, ']'), true
	case fastjson.TypeNumber:
		dst = value.MarshalTo(dst)
		if shouldStringifyNumberBytes(dst[start:]) {
			dst = strconv.AppendQuote(dst[:start], string(dst[start:]))
		}
		return dst, true
	default:
		return value.MarshalTo(dst), true
	}
}

func shouldStringifyNumberBytes(num []byte) bool {
	if bytes.IndexAny(num, ".eE") >= 0 {
		return false
	}

	start := 0
	negative := len(num) > 0 && num[0] == '-'
	if negative {
		start++
	}
	for start < len(num) && num[start] == '0' {
		start++
	}
	digits := num[start:]
	if len(digits) != 19 {
		return len(digits) > 19
	}
	limit := "9223372036854775807"
	if negative {
		limit = "9223372036854775808"
	}
	return bytes.Compare(digits, []byte(limit)) > 0
}

func processLine(rawLine []byte, buf *bytes.Buffer) error {
	var p processor
	return p.processLine(rawLine, buf)
}

func (p *processor) processLine(rawLine []byte, buf *bytes.Buffer) error {
	value, err := p.parser.ParseBytes(rawLine)
	if err != nil {
		return fmt.Errorf("json parse error: %w", err)
	}

	buf.Reset()
	buf.Grow(len(rawLine))
	output, keep := appendCleanJSON(buf.AvailableBuffer(), value)
	if !keep {
		output = append(output, "null"...)
	}
	_, _ = buf.Write(output)
	return nil
}

func run(input io.Reader, output io.Writer) error {
	reader := bufio.NewReaderSize(input, 4*1024*1024)
	writer := bufio.NewWriterSize(output, 4*1024*1024)
	buf := bytes.NewBuffer(make([]byte, 0, 64*1024))
	var proc processor

	for {
		line, err := reader.ReadBytes('\n')
		if err != nil && err != io.EOF {
			return fmt.Errorf("stdin read error: %w", err)
		}
		if len(line) == 0 && err == io.EOF {
			return writer.Flush()
		}

		line = bytes.TrimSuffix(line, []byte{'\n'})
		line = bytes.TrimSuffix(line, []byte{'\r'})
		if processErr := proc.processLine(line, buf); processErr != nil {
			return fmt.Errorf("line processing error: %w", processErr)
		}
		if _, writeErr := writer.Write(append(buf.Bytes(), '\n')); writeErr != nil {
			return fmt.Errorf("stdout write error: %w", writeErr)
		}
		if err == io.EOF {
			return writer.Flush()
		}
	}
}

func runChunked(input io.Reader, output io.Writer) error {
	reader := bufio.NewReaderSize(input, 4*1024*1024)
	writer := bufio.NewWriterSize(output, 4*1024*1024)
	buf := bytes.NewBuffer(make([]byte, 0, 64*1024))
	var proc processor

	for {
		var rows int
		if _, err := fmt.Fscanln(reader, &rows); err == io.EOF {
			return writer.Flush()
		} else if err != nil {
			return fmt.Errorf("chunk header read error: %w", err)
		}
		for range rows {
			line, err := reader.ReadBytes('\n')
			if err != nil {
				return fmt.Errorf("stdin read error: %w", err)
			}
			line = bytes.TrimSuffix(line, []byte{'\n'})
			line = bytes.TrimSuffix(line, []byte{'\r'})
			if err := proc.processLine(line, buf); err != nil {
				return fmt.Errorf("line processing error: %w", err)
			}
			if _, err := writer.Write(append(buf.Bytes(), '\n')); err != nil {
				return fmt.Errorf("stdout write error: %w", err)
			}
		}
		if err := writer.Flush(); err != nil {
			return fmt.Errorf("stdout flush error: %w", err)
		}
	}
}

func main() {
	chunked := flag.Bool("chunked", false, "read a row-count header before each input chunk")
	flag.Parse()
	runner := run
	if *chunked {
		runner = runChunked
	}
	if err := runner(os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
