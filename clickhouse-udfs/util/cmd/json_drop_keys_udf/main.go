package main

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"runtime/pprof"
	"slices"
	"strconv"
	"strings"
	"sync"

	"github.com/valyala/fastjson"
)

// a struct for hierarchical keys, e.g. if someone wants to drop "properties.foo.bar", works only for objects

// jsonKey is a tree of dot-separated paths to drop. A nil child marks the end of a path.
type jsonKey map[string]jsonKey

// resolveKey matches an object key against the filter one dot-separated segment at a time.
// The key "a.b" and the nested path {"a":{"b":...}} address the same property, so dropping "a.b" removes both
// without restructuring the document. It returns drop=true when the key is on or under a dropped path, and
// otherwise the filter for the key's value, which is nil when no dropped path continues below this key.
func resolveKey(keys jsonKey, key []byte) (childKeys jsonKey, drop bool) {
	for {
		segment, rest, dotted := bytes.Cut(key, []byte{'.'})
		child, ok := keys[string(segment)]
		if !ok {
			return nil, false
		}
		if child == nil {
			return nil, true
		}
		if !dotted {
			return child, false
		}
		keys, key = child, rest
	}
}

func writeJSONString(buf *bytes.Buffer, s []byte) {
	buf.WriteByte('"')
	start := 0
	for i := 0; i < len(s); i++ {
		ch := s[i]
		if ch >= 0x20 && ch != '\\' && ch != '"' {
			continue
		}
		if start < i {
			buf.Write(s[start:i])
		}
		switch ch {
		case '\\', '"':
			buf.WriteByte('\\')
			buf.WriteByte(ch)
		case '\b':
			buf.WriteString("\\b")
		case '\f':
			buf.WriteString("\\f")
		case '\n':
			buf.WriteString("\\n")
		case '\r':
			buf.WriteString("\\r")
		case '\t':
			buf.WriteString("\\t")
		default:
			buf.WriteString("\\u00")
			const hex = "0123456789abcdef"
			buf.WriteByte(hex[ch>>4])
			buf.WriteByte(hex[ch&0x0f])
		}
		start = i + 1
	}
	if start < len(s) {
		buf.Write(s[start:])
	}
	buf.WriteByte('"')
}

type cachedParser struct {
	fastjson.Parser
	maxInput int
}

var parserPool = sync.Pool{
	New: func() interface{} {
		return &cachedParser{}
	},
}

func processLine(keys jsonKey, rawLine []byte, buf *bytes.Buffer) error {
	parser := parserPool.Get().(*cachedParser)
	defer parserPool.Put(parser)
	if parser.maxInput > max(64*1024, 2*len(rawLine)) {
		parser.Parser = fastjson.Parser{}
		parser.maxInput = 0
	}
	parser.maxInput = max(parser.maxInput, len(rawLine))
	if buf.Cap() > max(64*1024, 2*len(rawLine)) {
		*buf = bytes.Buffer{}
	}

	value, err := parser.ParseBytes(rawLine)
	if err != nil {
		return fmt.Errorf("json parse error: %w", err)
	}

	buf.Reset()
	buf.Grow(len(rawLine))
	if keys == nil {
		keys = jsonKey{}
	}
	return writeFilteredJSON(buf, value, keys)
}

func writeFilteredJSON(buf *bytes.Buffer, value *fastjson.Value, keys jsonKey) error {
	switch value.Type() {
	case fastjson.TypeObject:
		obj, _ := value.Object()
		buf.WriteByte('{')
		first := true
		var err error
		obj.Visit(func(key []byte, child *fastjson.Value) {
			if err != nil {
				return
			}
			childKeys, drop := resolveKey(keys, key)
			if drop {
				return
			}
			if !first {
				buf.WriteByte(',')
			}
			first = false
			writeJSONString(buf, key)
			buf.WriteByte(':')
			err = writeFilteredJSON(buf, child, childKeys)
		})
		buf.WriteByte('}')
		return err
	case fastjson.TypeArray:
		values, _ := value.Array()
		buf.WriteByte('[')
		for i, child := range values {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := writeFilteredJSON(buf, child, keys); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case fastjson.TypeString:
		writeJSONString(buf, value.GetStringBytes())
	default:
		buf.Write(value.MarshalTo(buf.AvailableBuffer()))
	}
	return nil
}

func parseSingleQuotedArray(s string) ([]string, error) {
	s = strings.TrimSpace(s)
	if len(s) < 2 || s[0] != '[' || s[len(s)-1] != ']' {
		return nil, fmt.Errorf("expected array wrapped in []")
	}
	s = s[1 : len(s)-1] // strip [ ]

	var result []string
	for len(s) > 0 {
		s = strings.TrimLeft(s, " \t")
		if len(s) == 0 {
			break
		}
		if s[0] != '\'' {
			return nil, fmt.Errorf("expected single quote at start of string, got %q", s)
		}
		s = s[1:] // skip opening '

		var sb strings.Builder
		for {
			if len(s) == 0 {
				return nil, fmt.Errorf("unterminated string")
			}
			if s[0] == '\\' && len(s) > 1 && s[1] == '\'' {
				sb.WriteByte('\'')
				s = s[2:]
				continue
			}
			if s[0] == '\'' {
				s = s[1:] // skip closing '
				break
			}
			sb.WriteByte(s[0])
			s = s[1:]
		}
		result = append(result, sb.String())

		s = strings.TrimLeft(s, " \t")
		if len(s) > 0 && s[0] == ',' {
			s = s[1:]
		}
	}
	return result, nil
}

func makeKeyDict(keys []string) jsonKey {
	dict := make(jsonKey)
	for _, key := range keys {
		parts := strings.Split(key, ".")
		current := dict
		for i, part := range parts {
			child, exists := current[part]
			if exists && child == nil {
				break
			}
			if i == len(parts)-1 {
				current[part] = nil
			} else {
				if !exists {
					child = make(jsonKey)
					current[part] = child
				}
				current = child
			}
		}
	}
	return dict
}

func main() {
	cpuProfile := flag.String("cpuprofile", "", "write CPU profile to file")
	debugLog := flag.Bool("debug", false, "enable debug logging")
	rowBinary := flag.Bool("row-binary", false, "read (json String, keys Array(String)) RowBinary rows after a row-count header")
	flag.Parse()

	keysArg := flag.Arg(0)

	stdErr := os.Stderr
	if *debugLog {
		logFile, err := os.OpenFile("/tmp/json_drop_keys_udf.log", os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
		if err != nil {
			fmt.Fprintf(os.Stderr, "open log file error: %v\n", err)
			os.Exit(1)
		}
		defer logFile.Close()
		stdErr = logFile
		log.SetOutput(logFile)
		fmt.Fprintf(logFile, "keysToDrop: %s\n", keysArg)
	}

	var runner func(io.Reader, io.Writer) error
	if *rowBinary {
		if flag.NArg() > 0 {
			fmt.Fprintln(stdErr, "keys are a per-row argument in RowBinary mode, not a command-line argument")
			os.Exit(1)
		}
		runner = runRowBinary
	} else {
		keys, err := parseSingleQuotedArray(keysArg)
		if err != nil {
			fmt.Fprintf(stdErr, "keysToDrop parse error: %v\n", err)
			os.Exit(1)
		}
		keysToDrop := makeKeyDict(keys)
		runner = func(input io.Reader, output io.Writer) error {
			return run(input, output, keysToDrop)
		}
	}

	if *cpuProfile != "" {
		f, err := os.Create(*cpuProfile)
		if err != nil {
			fmt.Fprintf(stdErr, "cpuprofile create error: %v\n", err)
			os.Exit(1)
		}
		if err := pprof.StartCPUProfile(f); err != nil {
			_ = f.Close()
			fmt.Fprintf(stdErr, "cpuprofile start error: %v\n", err)
			os.Exit(1)
		}
		defer func() {
			pprof.StopCPUProfile()
			_ = f.Close()
		}()
	}

	if err := runner(os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(stdErr, err)
		os.Exit(1)
	}
}

func readLine(reader *bufio.Reader) ([]byte, error) {
	line, err := reader.ReadSlice('\n')
	if err != bufio.ErrBufferFull {
		return line, err
	}
	var full []byte
	for {
		full = append(full, line...)
		if err != bufio.ErrBufferFull {
			return full, err
		}
		line, err = reader.ReadSlice('\n')
	}
}

func run(input io.Reader, output io.Writer, keys jsonKey) error {
	reader := bufio.NewReaderSize(input, 64*1024)
	writer := bufio.NewWriterSize(output, 64*1024)
	buf := bytes.NewBuffer(make([]byte, 0, 64*1024))
	for {
		line, err := readLine(reader)
		if err != nil && err != io.EOF {
			return fmt.Errorf("stdin read error: %w", err)
		}
		if len(line) == 0 && err == io.EOF {
			return writer.Flush()
		}
		hadNewline := len(line) > 0 && line[len(line)-1] == '\n'
		line = bytes.TrimSuffix(line, []byte("\n"))
		line = bytes.TrimSuffix(line, []byte("\r"))
		if procErr := processLine(keys, line, buf); procErr != nil {
			return fmt.Errorf("line processing error: %w", procErr)
		}
		if _, writeErr := writer.Write(buf.Bytes()); writeErr != nil {
			return fmt.Errorf("stdout write error: %w", writeErr)
		}
		if hadNewline {
			if writeErr := writer.WriteByte('\n'); writeErr != nil {
				return fmt.Errorf("stdout write error: %w", writeErr)
			}
		}
		if err == io.EOF {
			return writer.Flush()
		}
	}
}

const (
	// Matches ClickHouse's default format_binary_max_string_size, so the limit only rejects corrupt lengths.
	maxRowBinaryJSONSize = 1 << 30
	maxRowBinaryKeyCount = 1 << 16
	maxRowBinaryKeySize  = 64 * 1024
)

// rowBinaryKeys keeps the filter for the most recent key array. A query sends the same array on every row,
// so the filter is rebuilt only when the encoded array changes.
type rowBinaryKeys struct {
	encoded []byte
	scratch []byte
	filter  jsonKey
}

func (k *rowBinaryKeys) read(reader *bufio.Reader) (jsonKey, error) {
	count, err := readRowBinaryLength(reader, maxRowBinaryKeyCount, "key array")
	if err != nil {
		return nil, err
	}
	k.scratch = binary.AppendUvarint(k.scratch[:0], uint64(count))
	for range count {
		size, err := readRowBinaryLength(reader, maxRowBinaryKeySize, "key")
		if err != nil {
			return nil, err
		}
		k.scratch = binary.AppendUvarint(k.scratch, uint64(size))
		if k.scratch, err = appendRowBinaryBytes(reader, k.scratch, size); err != nil {
			return nil, err
		}
	}
	if k.filter != nil && bytes.Equal(k.scratch, k.encoded) {
		return k.filter, nil
	}

	keys := make([]string, 0, count)
	_, offset := binary.Uvarint(k.scratch)
	for range count {
		size, n := binary.Uvarint(k.scratch[offset:])
		offset += n
		keys = append(keys, string(k.scratch[offset:offset+int(size)]))
		offset += int(size)
	}
	k.filter = makeKeyDict(keys)
	k.encoded, k.scratch = k.scratch, k.encoded
	return k.filter, nil
}

func readRowBinaryLength(reader *bufio.Reader, maxSize int, name string) (int, error) {
	length, err := binary.ReadUvarint(reader)
	if err != nil {
		return 0, fmt.Errorf("read %s length: %w", name, truncated(err))
	}
	if length > uint64(maxSize) {
		return 0, fmt.Errorf("%s length %d exceeds %d", name, length, maxSize)
	}
	return int(length), nil
}

func appendRowBinaryBytes(reader *bufio.Reader, dst []byte, size int) ([]byte, error) {
	start := len(dst)
	dst = slices.Grow(dst, size)[:start+size]
	if _, err := io.ReadFull(reader, dst[start:]); err != nil {
		return nil, fmt.Errorf("read RowBinary string: %w", truncated(err))
	}
	return dst, nil
}

// truncated reports a clean EOF inside a chunk as truncation, because the chunk header promised more rows.
func truncated(err error) error {
	if errors.Is(err, io.EOF) {
		return io.ErrUnexpectedEOF
	}
	return err
}

// runRowBinary serves the executable_pool function. ClickHouse keeps one process per pool slot across blocks and
// queries, and sends an ASCII row count before each chunk so the process knows when to flush its answer.
func runRowBinary(input io.Reader, output io.Writer) error {
	reader := bufio.NewReaderSize(input, 64*1024)
	writer := bufio.NewWriterSize(output, 64*1024)
	buf := bytes.NewBuffer(make([]byte, 0, 64*1024))
	var (
		row    []byte
		keys   rowBinaryKeys
		length [binary.MaxVarintLen64]byte
	)
	for {
		header, err := reader.ReadSlice('\n')
		if err == io.EOF && len(header) == 0 {
			return nil
		}
		if err != nil {
			return fmt.Errorf("chunk header read error: %w", err)
		}
		rows, err := strconv.ParseUint(string(header[:len(header)-1]), 10, 64)
		if err != nil {
			return fmt.Errorf("invalid chunk header: %w", err)
		}
		for range rows {
			size, err := readRowBinaryLength(reader, maxRowBinaryJSONSize, "JSON")
			if err != nil {
				return err
			}
			if cap(row) > max(64*1024, 2*size) {
				row = nil
			}
			if row, err = appendRowBinaryBytes(reader, row[:0], size); err != nil {
				return err
			}
			filter, err := keys.read(reader)
			if err != nil {
				return err
			}
			if err := processLine(filter, row, buf); err != nil {
				return fmt.Errorf("row processing error: %w", err)
			}
			n := binary.PutUvarint(length[:], uint64(buf.Len()))
			if _, err := writer.Write(length[:n]); err != nil {
				return fmt.Errorf("stdout write error: %w", err)
			}
			if _, err := writer.Write(buf.Bytes()); err != nil {
				return fmt.Errorf("stdout write error: %w", err)
			}
		}
		if err := writer.Flush(); err != nil {
			return fmt.Errorf("stdout flush error: %w", err)
		}
	}
}
