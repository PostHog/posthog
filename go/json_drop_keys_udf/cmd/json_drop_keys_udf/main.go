package main

import (
	"bufio"
	"bytes"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"runtime/pprof"
	"strings"
	"sync"

	"github.com/valyala/fastjson"
)

type emptyT struct{}

// a struct for hierarchical keys, e.g. if someone wants to drop "properties.foo.bar", works only for objects
type jsonKey map[string]jsonKey

type node interface {
	Write(*bytes.Buffer)
	DropKeys(keys jsonKey) node
}

type valueKind int

const (
	kindString valueKind = iota
	kindNumber
	kindBool
	kindNull
)

type valueNode struct {
	kind valueKind
	str  string
	num  string
	b    bool
}

func (v *valueNode) Write(buf *bytes.Buffer) {
	switch v.kind {
	case kindString:
		writeJSONString(buf, v.str)
	case kindNumber:
		buf.WriteString(v.num)
	case kindBool:
		if v.b {
			buf.WriteString("true")
		} else {
			buf.WriteString("false")
		}
	case kindNull:
		buf.WriteString("null")
	}
}

func (v *valueNode) DropKeys(jsonKey) node {
	return v
}

type objectEntry struct {
	key   string
	value node
}

type objectNode struct {
	entries []objectEntry
}

type entryInfo struct {
	firstNonEmpty int
	last          int
	hasNonEmpty   bool
}

var entryInfoPool = sync.Pool{
	New: func() interface{} {
		return make(map[string]entryInfo)
	},
}

func (o *objectNode) Write(buf *bytes.Buffer) {
	buf.WriteByte('{')
	for i, entry := range o.entries {
		if i > 0 {
			buf.WriteByte(',')
		}
		writeJSONString(buf, entry.key)
		buf.WriteByte(':')
		entry.value.Write(buf)
	}
	buf.WriteByte('}')
}

func (o *objectNode) DropKeys(keysToDrop jsonKey) node {
	if len(o.entries) == 0 {
		return o
	}

	o.entries = expandDottedEntries(o.entries)

	for i, e := range o.entries {
		if val, ok := keysToDrop[e.key]; ok && len(val) > 0 {
			o.entries[i].value = o.entries[i].value.DropKeys(val)
		}
	}

	writeIdx := 0
	for _, entry := range o.entries {
		if _, toDrop := keysToDrop[entry.key]; toDrop {
			continue
		}
		o.entries[writeIdx] = entry
		writeIdx++
	}
	o.entries = o.entries[:writeIdx]

	return o
}

type mergeKey struct {
	parent *objectNode
	key    string
}

var dottedIndexPool = sync.Pool{
	New: func() interface{} {
		return make(map[mergeKey]*objectNode)
	},
}

func expandDottedEntries(entries []objectEntry) []objectEntry {
	needsExpand := false
	for _, entry := range entries {
		if indexByte(entry.key, '.') >= 0 {
			needsExpand = true
			break
		}
	}
	if !needsExpand {
		return entries
	}

	expanded := make([]objectEntry, 0, len(entries))
	index := dottedIndexPool.Get().(map[mergeKey]*objectNode)
	for _, entry := range entries {
		if indexByte(entry.key, '.') < 0 {
			appendEntry(nil, &expanded, entry.key, entry.value, index)
			continue
		}
		insertDottedKey(nil, &expanded, entry.key, entry.value, index)
	}

	for key := range index {
		delete(index, key)
	}
	dottedIndexPool.Put(index)

	return expanded
}

func appendEntry(parent *objectNode, entries *[]objectEntry, key string, value node, index map[mergeKey]*objectNode) {
	*entries = append(*entries, objectEntry{key: key, value: value})
	mk := mergeKey{parent: parent, key: key}
	if obj, ok := value.(*objectNode); ok {
		index[mk] = obj
	} else {
		delete(index, mk)
	}
}

func insertDottedKey(parent *objectNode, entries *[]objectEntry, key string, value node, index map[mergeKey]*objectNode) {
	for {
		dot := indexByte(key, '.')
		if dot < 0 {
			appendEntry(parent, entries, key, value, index)
			return
		}
		head := key[:dot]
		rest := key[dot+1:]
		mk := mergeKey{parent: parent, key: head}
		target := index[mk]
		if target == nil {
			target = objectNodePool.Get().(*objectNode)
			target.entries = target.entries[:0]
			appendEntry(parent, entries, head, target, index)
		}
		parent = target
		entries = &parent.entries
		key = rest
	}
}

func indexByte(s string, c byte) int {
	for i := 0; i < len(s); i++ {
		if s[i] == c {
			return i
		}
	}
	return -1
}

type arrayNode struct {
	values []node
}

func (a *arrayNode) Write(buf *bytes.Buffer) {
	buf.WriteByte('[')
	for i, value := range a.values {
		if i > 0 {
			buf.WriteByte(',')
		}
		value.Write(buf)
	}
	buf.WriteByte(']')
}

func (a *arrayNode) DropKeys(jsonKey) node {
	for i := range a.values {
		a.values[i] = a.values[i].DropKeys(nil)
	}
	return a
}

func isNonEmptyValue(n node) bool {
	switch v := n.(type) {
	case *valueNode:
		switch v.kind {
		case kindNull:
			return false
		case kindString:
			return v.str != ""
		default:
			return true
		}
	default:
		return true
	}
}

func writeJSONString(buf *bytes.Buffer, s string) {
	buf.WriteByte('"')
	start := 0
	for i := 0; i < len(s); i++ {
		ch := s[i]
		if ch >= 0x20 && ch != '\\' && ch != '"' {
			continue
		}
		if start < i {
			buf.WriteString(s[start:i])
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
		buf.WriteString(s[start:])
	}
	buf.WriteByte('"')
}

var parserPool = sync.Pool{
	New: func() interface{} {
		return &fastjson.Parser{}
	},
}

var valueNodePool = sync.Pool{
	New: func() interface{} {
		return &valueNode{}
	},
}

var objectNodePool = sync.Pool{
	New: func() interface{} {
		return &objectNode{}
	},
}

var arrayNodePool = sync.Pool{
	New: func() interface{} {
		return &arrayNode{}
	},
}

func recycleNode(n node) {
	switch v := n.(type) {
	case *valueNode:
		v.str = ""
		v.num = ""
		valueNodePool.Put(v)
	case *objectNode:
		for _, entry := range v.entries {
			recycleNode(entry.value)
		}
		v.entries = v.entries[:0]
		objectNodePool.Put(v)
	case *arrayNode:
		for _, child := range v.values {
			recycleNode(child)
		}
		v.values = v.values[:0]
		arrayNodePool.Put(v)
	}
}

func convertFastJSON(value *fastjson.Value) (node, error) {
	switch value.Type() {
	case fastjson.TypeObject:
		obj, err := value.Object()
		if err != nil {
			return nil, err
		}

		objNode := objectNodePool.Get().(*objectNode)
		if cap(objNode.entries) >= obj.Len() {
			objNode.entries = objNode.entries[:0]
		} else {
			objNode.entries = make([]objectEntry, 0, obj.Len())
		}
		obj.Visit(func(key []byte, v *fastjson.Value) {
			child, convErr := convertFastJSON(v)
			if convErr != nil {
				err = convErr
				return
			}
			objNode.entries = append(objNode.entries, objectEntry{key: string(key), value: child})
		})
		if err != nil {
			return nil, err
		}

		return objNode, nil
	case fastjson.TypeArray:
		values, err := value.Array()
		if err != nil {
			return nil, err
		}

		arrNode := arrayNodePool.Get().(*arrayNode)
		if cap(arrNode.values) >= len(values) {
			arrNode.values = arrNode.values[:0]
		} else {
			arrNode.values = make([]node, 0, len(values))
		}
		for _, item := range values {
			child, convErr := convertFastJSON(item)
			if convErr != nil {
				return nil, convErr
			}
			arrNode.values = append(arrNode.values, child)
		}

		return arrNode, nil
	case fastjson.TypeString:
		vn := valueNodePool.Get().(*valueNode)
		vn.kind = kindString
		vn.str = string(value.GetStringBytes())
		vn.num = ""
		return vn, nil
	case fastjson.TypeNumber:
		num := value.String()
		vn := valueNodePool.Get().(*valueNode)
		vn.kind = kindNumber
		vn.num = num
		vn.str = ""
		return vn, nil
	case fastjson.TypeTrue:
		vn := valueNodePool.Get().(*valueNode)
		vn.kind = kindBool
		vn.b = true
		vn.str = ""
		vn.num = ""
		return vn, nil
	case fastjson.TypeFalse:
		vn := valueNodePool.Get().(*valueNode)
		vn.kind = kindBool
		vn.b = false
		vn.str = ""
		vn.num = ""
		return vn, nil
	case fastjson.TypeNull:
		vn := valueNodePool.Get().(*valueNode)
		vn.kind = kindNull
		vn.str = ""
		vn.num = ""
		return vn, nil
	default:
		return nil, fmt.Errorf("unexpected fastjson type %v", value.Type())
	}
}

func processLine(keys jsonKey, rawLine []byte, buf *bytes.Buffer) error {
	parser := parserPool.Get().(*fastjson.Parser)
	defer parserPool.Put(parser)

	value, err := parser.ParseBytes(rawLine)
	if err != nil {
		return fmt.Errorf("json parse error: %w", err)
	}

	parsed, err := convertFastJSON(value)
	if err != nil {
		return fmt.Errorf("json parse error: %w", err)
	}
	result := parsed.DropKeys(keys)
	buf.Reset()
	buf.Grow(len(rawLine))
	result.Write(buf)
	recycleNode(result)
	return nil
}

// parseSingleQuotedArray parses a Python-style array like ['a', 'b\'c']
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
	dict := make(jsonKey, len(keys))
	for _, key := range keys {
		dict[key] = nil
	}
	return dict
}

func main() {
	cpuProfile := flag.String("cpuprofile", "", "write CPU profile to file")
	flag.Parse()

	keysArg := flag.Arg(0)

	logFile, err := os.OpenFile("/tmp/json_drop_keys_udf.log", os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open log file error: %v\n", err)
		os.Exit(1)
	}
	defer logFile.Close()
	log.SetOutput(logFile)
	fmt.Fprintf(logFile, "keysToDrop: %s\n", keysArg)

	keys, err := parseSingleQuotedArray(keysArg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "keysToDrop parse error: %v\n", err)
		os.Exit(1)
	}
	keysToDrop := makeKeyDict(keys)

	if *cpuProfile != "" {
		f, err := os.Create(*cpuProfile)
		if err != nil {
			fmt.Fprintf(os.Stderr, "cpuprofile create error: %v\n", err)
			os.Exit(1)
		}
		if err := pprof.StartCPUProfile(f); err != nil {
			_ = f.Close()
			fmt.Fprintf(os.Stderr, "cpuprofile start error: %v\n", err)
			os.Exit(1)
		}
		defer func() {
			pprof.StopCPUProfile()
			_ = f.Close()
		}()
	}

	reader := bufio.NewReaderSize(os.Stdin, 4*1024*1024)
	writer := bufio.NewWriterSize(os.Stdout, 4*1024*1024)
	defer writer.Flush()
	buf := bytes.NewBuffer(make([]byte, 0, 64*1024))

	for {
		line, err := reader.ReadBytes('\n')
		if err != nil && err != io.EOF {
			fmt.Fprintf(os.Stderr, "stdin read error: %v\n", err)
			return
		}

		if len(line) == 0 && err == io.EOF {
			return
		}

		hadNewline := false
		n := len(line)
		if n > 0 && line[n-1] == '\n' {
			hadNewline = true
			n--
		}
		if n > 0 && line[n-1] == '\r' {
			n--
		}
		line = line[:n]

		procErr := processLine(keysToDrop, line, buf)
		if procErr != nil {
			fmt.Fprintf(os.Stderr, "line processing error: %v\n", procErr)
			os.Exit(1)
		}

		_, _ = writer.Write(buf.Bytes())
		if hadNewline {
			_, _ = writer.WriteString("\n")
		}

		if err == io.EOF {
			return
		}
	}
}
