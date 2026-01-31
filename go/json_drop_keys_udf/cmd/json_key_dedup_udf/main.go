package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"runtime/pprof"
	"sync"

	"github.com/valyala/fastjson"
)

type node interface {
	Write(*bytes.Buffer)
	DropKeys(keys []string) node
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

func (v *valueNode) DropKeys([]string) node {
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

func (o *objectNode) DropKeys([]string) node {
	if len(o.entries) == 0 {
		return o
	}

	o.entries = expandDottedEntries(o.entries)

	for i := range o.entries {
		o.entries[i].value = o.entries[i].value.DropKeys(nil)
	}

	infoMap := entryInfoPool.Get().(map[string]entryInfo)
	for i, entry := range o.entries {
		info := infoMap[entry.key]
		info.last = i
		if !info.hasNonEmpty && isNonEmptyValue(entry.value) {
			info.hasNonEmpty = true
			info.firstNonEmpty = i
		}
		infoMap[entry.key] = info
	}

	writeIdx := 0
	for i, entry := range o.entries {
		info := infoMap[entry.key]
		keep := false
		if info.hasNonEmpty {
			keep = info.firstNonEmpty == i
		} else {
			keep = info.last == i
		}
		if keep {
			o.entries[writeIdx] = entry
			writeIdx++
		}
	}
	o.entries = o.entries[:writeIdx]

	for key := range infoMap {
		delete(infoMap, key)
	}
	entryInfoPool.Put(infoMap)
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

func (a *arrayNode) DropKeys([]string) node {
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
		if shouldStringifyNumber(num) {
			vn.kind = kindString
			vn.str = num
			vn.num = ""
		} else {
			vn.kind = kindNumber
			vn.num = num
			vn.str = ""
		}
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

func shouldStringifyNumber(num string) bool {
	if len(num) == 0 {
		return false
	}

	// Check for float indicators
	for i := 0; i < len(num); i++ {
		c := num[i]
		if c == '.' || c == 'e' || c == 'E' {
			return false
		}
	}

	start := 0
	neg := num[0] == '-'
	if neg {
		start = 1
	}

	// Skip leading zeros
	for start < len(num) && num[start] == '0' {
		start++
	}

	digitLen := len(num) - start
	if digitLen == 0 {
		return false // It's just zeros
	}

	const maxLen = 19 // len("9223372036854775807")
	if digitLen < maxLen {
		return false
	}
	if digitLen > maxLen {
		return true
	}

	// Exactly maxLen digits - compare lexicographically
	digits := num[start:]
	if neg {
		const minInt64Abs = "9223372036854775808"
		return digits > minInt64Abs
	}
	const maxInt64 = "9223372036854775807"
	return digits > maxInt64
}

func processLine(keys []string, rawLine []byte, buf *bytes.Buffer) error {
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

func main() {
	cpuProfile := flag.String("cpuprofile", "", "write CPU profile to file")
	keysToDrop := flag.String("keysToDrop", "", "comma-separated list of keys to drop")
	flag.Parse()

	var keys []string
	if err := json.Unmarshal([]byte(*keysToDrop), &keys); err != nil {
		fmt.Fprintf(os.Stderr, "keysToDrop parse error: %v\n", err)
		os.Exit(1)
	}

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

		procErr := processLine(keys, line, buf)
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
