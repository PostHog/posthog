package main

import (
	"bufio"
	"bytes"
	"flag"
	"fmt"
	"io"
	"os"
	"runtime/pprof"
	"strings"
	"unsafe"
)

type normalizationKind byte

const (
	normalizationNone normalizationKind = iota
	normalizationStringArray
	normalizationObjectArray
)

type pathRule struct {
	normalization normalizationKind
	children      map[string]*pathRule
}

var eventPropertyRules = makeEventPropertyRules()

const unparsablePropertiesKey = "$properties_unparsable"

var droppedEventPropertyKeys = map[string]struct{}{
	"$ai_input":                          {},
	"$ai_output":                         {},
	"$ai_output_choices":                 {},
	"$ai_input_state":                    {},
	"$ai_output_state":                   {},
	"$ai_tools":                          {},
	"ph_product_tours":                   {},
	"$session_recording_remote_config":   {},
	"$product_tours_activated":           {},
	"$product_tours_enabled_server_side": {},
	"$surveys_activated":                 {},
	"$active_feature_flags":              {},
	"$feature_flag_payload":              {},
	"$feature_flag_bootstrapped_payload": {},
	"$feature_flag_original_payload":     {},
	"$feature_flag_payloads":             {},
	"$set":                               {},
	"$set_once":                          {},
	"$unset":                             {},
	"$transformations_succeeded":         {},
	"$transformations_skipped":           {},
	unparsablePropertiesKey:              {},
}

func makePathRules(paths ...string) *pathRule {
	root := &pathRule{children: make(map[string]*pathRule, len(paths))}
	addPathRules(root, normalizationStringArray, paths...)
	return root
}

func addPathRules(root *pathRule, normalization normalizationKind, paths ...string) {
	for _, path := range paths {
		node := root
		for {
			part, rest, ok := strings.Cut(path, ".")
			child := node.children[part]
			if child == nil {
				child = &pathRule{children: make(map[string]*pathRule)}
				node.children[part] = child
			}
			if !ok {
				child.normalization = normalization
				break
			}
			node = child
			path = rest
		}
	}
}

func makeEventPropertyRules() *pathRule {
	root := makePathRules(
		"$exception_functions",
		"$exception_sources",
		"$exception_types",
		"$exception_values",
		"$mcp_listed_tool_names",
	)
	addPathRules(root, normalizationObjectArray,
		"$exception_list",
	)
	return root
}

type valueKind byte

const (
	kindString valueKind = iota
	kindNumber
	kindBool
	kindNull
	kindObject
	kindArray
)

type value struct {
	kind    valueKind
	s       string
	b       bool
	entries []entry
	values  []*value
}

type entry struct {
	key   string
	value *value
}

type entryInfo struct {
	firstNonEmpty int
	last          int
	hasNonEmpty   bool
}

type mergeKey struct {
	parent *value
	key    string
}

type processor struct {
	data      []byte
	pos       int
	mutated   bool
	rawSafe   bool
	free      []*value
	info      map[string]entryInfo
	index     map[mergeKey]*value
	stringBuf bytes.Buffer
}

func processLine(rawLine []byte, buf *bytes.Buffer) error {
	var proc processor
	return proc.processLine(rawLine, buf)
}

func (p *processor) processLine(rawLine []byte, buf *bytes.Buffer) error {
	p.data = rawLine
	p.pos = 0
	p.mutated = false
	p.rawSafe = true

	parsed, err := p.parseValue()
	if err != nil {
		return fmt.Errorf("json parse error: %w", err)
	}
	p.skipWS()
	if p.pos != len(p.data) {
		p.recycle(parsed)
		return fmt.Errorf("json parse error: trailing data at byte %d", p.pos)
	}

	cleaned, err := p.cleanEventProperties(parsed)
	if err != nil {
		p.recycle(parsed)
		return fmt.Errorf("json clean error: %w", err)
	}

	buf.Reset()
	buf.Grow(len(rawLine))
	if !p.mutated && p.rawSafe {
		buf.Write(rawLine)
	} else {
		p.writeValue(buf, cleaned)
	}
	p.recycle(cleaned)
	return nil
}

func (p *processor) cleanEventProperties(v *value) (*value, error) {
	if v.kind != kindObject {
		return p.cleanNode(eventPropertyRules, v)
	}

	var featureFlags *value
	hasFeatureProperties := false
	for _, property := range v.entries {
		if strings.HasPrefix(property.key, "$feature/") {
			hasFeatureProperties = true
		} else if property.key == "$feature_flags" && property.value.kind == kindObject && featureFlags == nil {
			featureFlags = property.value
		}
	}
	createdFeatureFlags := hasFeatureProperties && featureFlags == nil
	if createdFeatureFlags {
		featureFlags = p.newValue(kindObject)
	}

	writeIdx := 0
	for _, property := range v.entries {
		_, drop := droppedEventPropertyKeys[property.key]
		if drop || hasFeatureProperties && property.key == "$feature_flags" && property.value != featureFlags {
			p.mutated = true
			p.recycle(property.value)
			continue
		}
		if name, ok := strings.CutPrefix(property.key, "$feature/"); ok {
			featureFlags.entries = append(featureFlags.entries, entry{key: name, value: property.value})
			p.mutated = true
			continue
		}
		v.entries[writeIdx] = property
		writeIdx++
	}
	v.entries = v.entries[:writeIdx]
	if createdFeatureFlags {
		v.entries = append(v.entries, entry{key: "$feature_flags", value: featureFlags})
	}
	return p.cleanNode(eventPropertyRules, v)
}

func (p *processor) newValue(kind valueKind) *value {
	n := len(p.free)
	if n == 0 {
		return &value{kind: kind}
	}
	v := p.free[n-1]
	p.free = p.free[:n-1]
	v.kind = kind
	v.s = ""
	v.b = false
	v.entries = v.entries[:0]
	v.values = v.values[:0]
	return v
}

func (p *processor) recycle(v *value) {
	if v == nil {
		return
	}
	for _, entry := range v.entries {
		p.recycle(entry.value)
	}
	for _, child := range v.values {
		p.recycle(child)
	}
	v.s = ""
	v.b = false
	v.entries = v.entries[:0]
	v.values = v.values[:0]
	p.free = append(p.free, v)
}

func (p *processor) parseValue() (*value, error) {
	p.skipWS()
	if p.pos >= len(p.data) {
		return nil, fmt.Errorf("unexpected end of input")
	}

	switch p.data[p.pos] {
	case '{':
		return p.parseObject()
	case '[':
		return p.parseArray()
	case '"':
		s, err := p.parseString()
		if err != nil {
			return nil, err
		}
		v := p.newValue(kindString)
		v.s = s
		return v, nil
	case 't':
		if !p.consumeLiteral("true") {
			return nil, fmt.Errorf("invalid literal at byte %d", p.pos)
		}
		v := p.newValue(kindBool)
		v.b = true
		return v, nil
	case 'f':
		if !p.consumeLiteral("false") {
			return nil, fmt.Errorf("invalid literal at byte %d", p.pos)
		}
		return p.newValue(kindBool), nil
	case 'n':
		if !p.consumeLiteral("null") {
			return nil, fmt.Errorf("invalid literal at byte %d", p.pos)
		}
		return p.newValue(kindNull), nil
	default:
		if p.data[p.pos] == '-' || isDigit(p.data[p.pos]) {
			num, err := p.parseNumber()
			if err != nil {
				return nil, err
			}
			v := p.newValue(kindNumber)
			if shouldStringifyNumber(num) {
				p.mutated = true
				v.kind = kindString
			}
			v.s = num
			return v, nil
		}
		return nil, fmt.Errorf("unexpected byte %q at byte %d", p.data[p.pos], p.pos)
	}
}

func (p *processor) parseObject() (*value, error) {
	p.pos++
	obj := p.newValue(kindObject)
	p.skipWS()
	if p.consumeByte('}') {
		return obj, nil
	}

	for {
		p.skipWS()
		if p.pos >= len(p.data) || p.data[p.pos] != '"' {
			p.recycle(obj)
			return nil, fmt.Errorf("expected object key at byte %d", p.pos)
		}
		key, err := p.parseString()
		if err != nil {
			p.recycle(obj)
			return nil, err
		}
		p.skipWS()
		if !p.consumeByte(':') {
			p.recycle(obj)
			return nil, fmt.Errorf("expected ':' at byte %d", p.pos)
		}
		child, err := p.parseValue()
		if err != nil {
			p.recycle(obj)
			return nil, err
		}
		obj.entries = append(obj.entries, entry{key: key, value: child})
		p.skipWS()
		if p.consumeByte('}') {
			return obj, nil
		}
		if !p.consumeByte(',') {
			p.recycle(obj)
			return nil, fmt.Errorf("expected ',' or '}' at byte %d", p.pos)
		}
	}
}

func (p *processor) parseArray() (*value, error) {
	p.pos++
	arr := p.newValue(kindArray)
	p.skipWS()
	if p.consumeByte(']') {
		return arr, nil
	}

	for {
		child, err := p.parseValue()
		if err != nil {
			p.recycle(arr)
			return nil, err
		}
		arr.values = append(arr.values, child)
		p.skipWS()
		if p.consumeByte(']') {
			return arr, nil
		}
		if !p.consumeByte(',') {
			p.recycle(arr)
			return nil, fmt.Errorf("expected ',' or ']' at byte %d", p.pos)
		}
	}
}

func (p *processor) parseString() (string, error) {
	quote := p.pos
	p.pos++
	start := p.pos
	for p.pos < len(p.data) {
		c := p.data[p.pos]
		switch {
		case c == '"':
			s := borrowedString(p.data[start:p.pos])
			p.pos++
			return s, nil
		case c == '\\':
			return p.parseEscapedString(quote)
		case c < 0x20:
			return "", fmt.Errorf("invalid control character at byte %d", p.pos)
		default:
			p.pos++
		}
	}
	return "", fmt.Errorf("unterminated string at byte %d", quote)
}

func (p *processor) parseEscapedString(quote int) (string, error) {
	p.pos = quote + 1
	p.stringBuf.Reset()

	for p.pos < len(p.data) {
		c := p.data[p.pos]
		switch {
		case c == '"':
			p.pos++
			return p.stringBuf.String(), nil
		case c == '\\':
			p.pos++
			if p.pos >= len(p.data) {
				return "", fmt.Errorf("unterminated escape at byte %d", p.pos)
			}
			switch p.data[p.pos] {
			case '"', '\\', '/':
				if p.data[p.pos] == '/' {
					p.rawSafe = false
				}
				p.stringBuf.WriteByte(p.data[p.pos])
				p.pos++
			case 'b':
				p.stringBuf.WriteByte('\b')
				p.pos++
			case 'f':
				p.stringBuf.WriteByte('\f')
				p.pos++
			case 'n':
				p.stringBuf.WriteByte('\n')
				p.pos++
			case 'r':
				p.stringBuf.WriteByte('\r')
				p.pos++
			case 't':
				p.stringBuf.WriteByte('\t')
				p.pos++
			case 'u':
				p.rawSafe = false
				r, err := p.parseUnicodeEscape()
				if err != nil {
					return "", err
				}
				p.stringBuf.WriteRune(r)
			default:
				return "", fmt.Errorf("invalid escape at byte %d", p.pos)
			}
		case c < 0x20:
			return "", fmt.Errorf("invalid control character at byte %d", p.pos)
		default:
			p.stringBuf.WriteByte(c)
			p.pos++
		}
	}
	return "", fmt.Errorf("unterminated string at byte %d", quote)
}

func (p *processor) parseUnicodeEscape() (rune, error) {
	if p.pos+5 > len(p.data) {
		return 0, fmt.Errorf("short unicode escape at byte %d", p.pos)
	}
	r, ok := hexRune(p.data[p.pos+1 : p.pos+5])
	if !ok {
		return 0, fmt.Errorf("invalid unicode escape at byte %d", p.pos)
	}
	p.pos += 5

	if r < 0xd800 || r > 0xdbff {
		return r, nil
	}
	if p.pos+6 > len(p.data) || p.data[p.pos] != '\\' || p.data[p.pos+1] != 'u' {
		return 0, fmt.Errorf("missing low surrogate at byte %d", p.pos)
	}
	low, ok := hexRune(p.data[p.pos+2 : p.pos+6])
	if !ok || low < 0xdc00 || low > 0xdfff {
		return 0, fmt.Errorf("invalid low surrogate at byte %d", p.pos)
	}
	p.pos += 6
	return 0x10000 + ((r - 0xd800) << 10) + (low - 0xdc00), nil
}

func hexRune(b []byte) (rune, bool) {
	var r rune
	for _, c := range b {
		r <<= 4
		switch {
		case c >= '0' && c <= '9':
			r += rune(c - '0')
		case c >= 'a' && c <= 'f':
			r += rune(c-'a') + 10
		case c >= 'A' && c <= 'F':
			r += rune(c-'A') + 10
		default:
			return 0, false
		}
	}
	return r, true
}

func (p *processor) parseNumber() (string, error) {
	start := p.pos
	if p.consumeByte('-') && p.pos >= len(p.data) {
		return "", fmt.Errorf("short number at byte %d", start)
	}
	if p.pos >= len(p.data) {
		return "", fmt.Errorf("short number at byte %d", start)
	}

	if p.data[p.pos] == '0' {
		p.pos++
	} else if p.data[p.pos] >= '1' && p.data[p.pos] <= '9' {
		for p.pos < len(p.data) && isDigit(p.data[p.pos]) {
			p.pos++
		}
	} else {
		return "", fmt.Errorf("invalid number at byte %d", start)
	}

	if p.pos < len(p.data) && p.data[p.pos] == '.' {
		p.pos++
		if p.pos >= len(p.data) || !isDigit(p.data[p.pos]) {
			return "", fmt.Errorf("invalid fraction at byte %d", p.pos)
		}
		for p.pos < len(p.data) && isDigit(p.data[p.pos]) {
			p.pos++
		}
	}

	if p.pos < len(p.data) && (p.data[p.pos] == 'e' || p.data[p.pos] == 'E') {
		p.pos++
		if p.pos < len(p.data) && (p.data[p.pos] == '+' || p.data[p.pos] == '-') {
			p.pos++
		}
		if p.pos >= len(p.data) || !isDigit(p.data[p.pos]) {
			return "", fmt.Errorf("invalid exponent at byte %d", p.pos)
		}
		for p.pos < len(p.data) && isDigit(p.data[p.pos]) {
			p.pos++
		}
	}

	return borrowedString(p.data[start:p.pos]), nil
}

func (p *processor) skipWS() {
	for p.pos < len(p.data) {
		switch p.data[p.pos] {
		case ' ', '\n', '\r', '\t':
			p.rawSafe = false
			p.pos++
		default:
			return
		}
	}
}

func (p *processor) consumeByte(c byte) bool {
	if p.pos < len(p.data) && p.data[p.pos] == c {
		p.pos++
		return true
	}
	return false
}

func (p *processor) consumeLiteral(s string) bool {
	if len(p.data)-p.pos < len(s) {
		return false
	}
	for i := 0; i < len(s); i++ {
		if p.data[p.pos+i] != s[i] {
			return false
		}
	}
	p.pos += len(s)
	return true
}

func (p *processor) cleanNode(pathRules *pathRule, v *value) (*value, error) {
	switch v.kind {
	case kindObject:
		if err := p.cleanObject(pathRules, v); err != nil {
			return nil, err
		}
	case kindArray:
		for i, child := range v.values {
			cleaned, err := p.cleanNode(pathRules, child)
			if err != nil {
				return nil, err
			}
			v.values[i] = cleaned
		}
	}
	return v, nil
}

func (p *processor) cleanObject(pathRules *pathRule, obj *value) error {
	obj.entries = p.expandDottedEntries(obj.entries)

	var unparsable bytes.Buffer
	writeIdx := 0
	for readIdx, entry := range obj.entries {
		var childPathRules *pathRule
		if pathRules != nil {
			childPathRules = pathRules.children[entry.key]
		}
		cleaned, err := p.cleanNode(childPathRules, entry.value)
		if err != nil {
			p.retainUnprocessedEntries(obj, writeIdx, readIdx)
			return err
		}
		if childPathRules != nil && childPathRules.normalization != normalizationNone {
			p.mutated = true
			original := cleaned
			cleaned, err = p.normalizeValue(childPathRules.normalization, cleaned)
			if err != nil {
				cleaned = original
				if unparsable.Len() == 0 {
					unparsable.WriteByte('{')
				} else {
					unparsable.WriteByte(',')
				}
				writeJSONString(&unparsable, entry.key)
				unparsable.WriteByte(':')
				p.writeValue(&unparsable, cleaned)
				cleaned = p.reuseAsEmptyArray(cleaned)
			}
		}
		if cleaned.kind == kindNull {
			p.mutated = true
			p.recycle(cleaned)
			continue
		}
		obj.entries[writeIdx] = entry
		obj.entries[writeIdx].value = cleaned
		writeIdx++
	}
	obj.entries = obj.entries[:writeIdx]
	if unparsable.Len() > 0 {
		unparsable.WriteByte('}')
		marker := p.newValue(kindString)
		marker.s = unparsable.String()
		obj.entries = append(obj.entries, entry{key: unparsablePropertiesKey, value: marker})
	}
	p.deduplicateEntries(obj)
	return nil
}

func (p *processor) retainUnprocessedEntries(obj *value, writeIdx, readIdx int) {
	remaining := len(obj.entries) - readIdx
	copy(obj.entries[writeIdx:writeIdx+remaining], obj.entries[readIdx:])
	obj.entries = obj.entries[:writeIdx+remaining]
}

func (p *processor) expandDottedEntries(entries []entry) []entry {
	needsExpand := false
	for _, entry := range entries {
		if strings.IndexByte(entry.key, '.') >= 0 {
			needsExpand = true
			break
		}
	}
	if !needsExpand {
		return entries
	}
	p.mutated = true

	expanded := make([]entry, 0, len(entries))
	if p.index == nil {
		p.index = make(map[mergeKey]*value, len(entries))
	}
	for key := range p.index {
		delete(p.index, key)
	}

	for _, entry := range entries {
		if strings.IndexByte(entry.key, '.') < 0 {
			p.appendEntry(nil, &expanded, entry.key, entry.value)
		} else {
			p.insertDottedKey(nil, &expanded, entry.key, entry.value)
		}
	}

	for key := range p.index {
		delete(p.index, key)
	}
	return expanded
}

func (p *processor) appendEntry(parent *value, entries *[]entry, key string, child *value) {
	*entries = append(*entries, entry{key: key, value: child})
	mk := mergeKey{parent: parent, key: key}
	if child.kind == kindObject {
		p.index[mk] = child
	} else {
		delete(p.index, mk)
	}
}

func (p *processor) insertDottedKey(parent *value, entries *[]entry, key string, child *value) {
	for {
		dot := strings.IndexByte(key, '.')
		if dot < 0 {
			p.appendEntry(parent, entries, key, child)
			return
		}

		head := key[:dot]
		rest := key[dot+1:]
		mk := mergeKey{parent: parent, key: head}
		target := p.index[mk]
		if target == nil {
			target = p.newValue(kindObject)
			p.appendEntry(parent, entries, head, target)
		}
		parent = target
		entries = &parent.entries
		key = rest
	}
}

func (p *processor) deduplicateEntries(obj *value) {
	if len(obj.entries) == 0 {
		return
	}
	if p.info == nil {
		p.info = make(map[string]entryInfo, len(obj.entries))
	}
	for key := range p.info {
		delete(p.info, key)
	}

	for i, entry := range obj.entries {
		info := p.info[entry.key]
		info.last = i
		if !info.hasNonEmpty && isNonEmptyValue(entry.value) {
			info.hasNonEmpty = true
			info.firstNonEmpty = i
		}
		p.info[entry.key] = info
	}

	writeIdx := 0
	for i, entry := range obj.entries {
		info := p.info[entry.key]
		keep := info.last == i
		if info.hasNonEmpty {
			keep = info.firstNonEmpty == i
		}
		if keep {
			obj.entries[writeIdx] = entry
			writeIdx++
		} else {
			p.mutated = true
			p.recycle(entry.value)
		}
	}
	obj.entries = obj.entries[:writeIdx]

	for key := range p.info {
		delete(p.info, key)
	}
}

func (p *processor) normalizeValue(normalization normalizationKind, v *value) (*value, error) {
	switch normalization {
	case normalizationStringArray:
		return p.coerceStringArray(v)
	case normalizationObjectArray:
		return p.coerceObjectArray(v)
	default:
		return v, nil
	}
}

func (p *processor) coerceObjectArray(v *value) (*value, error) {
	switch v.kind {
	case kindArray:
		for _, child := range v.values {
			if child.kind != kindObject {
				return nil, fmt.Errorf("cannot coerce array containing %s to Array(JSON)", valueKindName(child.kind))
			}
		}
		return v, nil
	case kindObject:
		arr := p.newValue(kindArray)
		arr.values = append(arr.values, v)
		return arr, nil
	case kindNull:
		return p.reuseAsEmptyArray(v), nil
	case kindString:
		raw := strings.TrimSpace(v.s)
		if isNullishString(raw) {
			return p.reuseAsEmptyArray(v), nil
		}
		parsed, err := p.parseStringifiedJSON(raw)
		if err != nil {
			return nil, err
		}
		normalized, err := p.coerceObjectArray(parsed)
		if err != nil {
			p.recycle(parsed)
			return nil, err
		}
		p.recycle(v)
		return normalized, nil
	default:
		return nil, fmt.Errorf("cannot coerce %s to Array(JSON)", valueKindName(v.kind))
	}
}

func isNullishString(s string) bool {
	return s == "" || strings.EqualFold(s, "null") || strings.EqualFold(s, "undefined")
}

func valueKindName(kind valueKind) string {
	switch kind {
	case kindString:
		return "String"
	case kindNumber:
		return "Number"
	case kindBool:
		return "Bool"
	case kindNull:
		return "Null"
	case kindObject:
		return "Object"
	case kindArray:
		return "Array"
	default:
		return "unknown value"
	}
}

func (p *processor) coerceStringArray(v *value) (*value, error) {
	switch v.kind {
	case kindArray:
		oldValues := v.values
		v.values = v.values[:0]
		for _, child := range oldValues {
			s := p.nodeString(child)
			p.recycle(child)
			str := p.newValue(kindString)
			str.s = s
			v.values = append(v.values, str)
		}
		return v, nil
	case kindObject:
		if len(v.entries) == 0 {
			return p.reuseAsEmptyArray(v), nil
		}
		s := p.nodeString(v)
		return p.reuseAsStringArray(v, s), nil
	case kindNull:
		return p.reuseAsEmptyArray(v), nil
	case kindString:
		trimmed := strings.TrimSpace(v.s)
		if isEmptyArrayString(trimmed) {
			return p.reuseAsEmptyArray(v), nil
		}
		if parsed, ok, err := p.parseStringifiedJSONArray(trimmed); err != nil {
			return nil, err
		} else if ok {
			p.recycle(v)
			return p.coerceStringArray(parsed)
		}
		return p.reuseAsStringArray(v, v.s), nil
	default:
		return p.reuseAsStringArray(v, p.nodeString(v)), nil
	}
}

func (p *processor) resetValue(v *value, kind valueKind) {
	for _, entry := range v.entries {
		p.recycle(entry.value)
	}
	for _, child := range v.values {
		p.recycle(child)
	}
	v.kind = kind
	v.s = ""
	v.b = false
	v.entries = v.entries[:0]
	v.values = v.values[:0]
}

func (p *processor) reuseAsEmptyArray(v *value) *value {
	p.resetValue(v, kindArray)
	return v
}

func (p *processor) reuseAsStringArray(v *value, s string) *value {
	p.reuseAsEmptyArray(v)
	child := p.newValue(kindString)
	child.s = s
	v.values = append(v.values, child)
	return v
}

func (p *processor) parseStringifiedJSON(raw string) (*value, error) {
	if raw == "" || (raw[0] != '[' && raw[0] != '{') {
		return nil, fmt.Errorf("cannot coerce %q to Array(JSON)", raw)
	}

	oldData, oldPos := p.data, p.pos
	p.data = borrowedBytes(raw)
	p.pos = 0
	parsed, err := p.parseValue()
	if err != nil {
		p.data, p.pos = oldData, oldPos
		return nil, fmt.Errorf("cannot coerce %q to Array(JSON): %w", raw, err)
	}
	p.skipWS()
	if p.pos != len(p.data) {
		p.recycle(parsed)
		p.data, p.pos = oldData, oldPos
		return nil, fmt.Errorf("cannot coerce %q to Array(JSON): trailing data", raw)
	}
	cleaned, err := p.cleanNode(nil, parsed)
	p.data, p.pos = oldData, oldPos
	if err != nil {
		p.recycle(parsed)
		return nil, err
	}
	return cleaned, nil
}

func (p *processor) parseStringifiedJSONArray(raw string) (*value, bool, error) {
	if raw == "" || raw[0] != '[' {
		return nil, false, nil
	}

	oldData, oldPos := p.data, p.pos
	p.data = borrowedBytes(raw)
	p.pos = 0
	parsed, err := p.parseValue()
	if err != nil {
		p.data, p.pos = oldData, oldPos
		return nil, false, nil
	}
	p.skipWS()
	if p.pos != len(p.data) || parsed.kind != kindArray {
		p.recycle(parsed)
		p.data, p.pos = oldData, oldPos
		return nil, false, nil
	}
	cleaned, err := p.cleanNode(nil, parsed)
	p.data, p.pos = oldData, oldPos
	if err != nil {
		return nil, false, err
	}
	return cleaned, true, nil
}

func (p *processor) nodeString(v *value) string {
	switch v.kind {
	case kindString, kindNumber:
		return v.s
	case kindBool:
		if v.b {
			return "true"
		}
		return "false"
	case kindNull:
		return ""
	default:
		p.stringBuf.Reset()
		p.writeValue(&p.stringBuf, v)
		return p.stringBuf.String()
	}
}

func (p *processor) writeValue(buf *bytes.Buffer, v *value) {
	switch v.kind {
	case kindString:
		writeJSONString(buf, v.s)
	case kindNumber:
		buf.WriteString(v.s)
	case kindBool:
		if v.b {
			buf.WriteString("true")
		} else {
			buf.WriteString("false")
		}
	case kindNull:
		buf.WriteString("null")
	case kindObject:
		buf.WriteByte('{')
		for i, entry := range v.entries {
			if i > 0 {
				buf.WriteByte(',')
			}
			writeJSONString(buf, entry.key)
			buf.WriteByte(':')
			p.writeValue(buf, entry.value)
		}
		buf.WriteByte('}')
	case kindArray:
		buf.WriteByte('[')
		for i, child := range v.values {
			if i > 0 {
				buf.WriteByte(',')
			}
			p.writeValue(buf, child)
		}
		buf.WriteByte(']')
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

func isNonEmptyValue(v *value) bool {
	switch v.kind {
	case kindNull:
		return false
	case kindString:
		return v.s != ""
	case kindArray:
		return len(v.values) > 0
	case kindObject:
		return len(v.entries) > 0
	default:
		return true
	}
}

func isEmptyArrayString(s string) bool {
	switch len(s) {
	case 0:
		return true
	case 4:
		return strings.EqualFold(s, "null")
	case 9:
		return strings.EqualFold(s, "undefined")
	default:
		return false
	}
}

func shouldStringifyNumber(num string) bool {
	if len(num) == 0 {
		return false
	}

	for i := 0; i < len(num); i++ {
		switch num[i] {
		case '.', 'e', 'E':
			return false
		}
	}

	start := 0
	neg := num[0] == '-'
	if neg {
		start = 1
	}
	for start < len(num) && num[start] == '0' {
		start++
	}

	digitLen := len(num) - start
	if digitLen == 0 {
		return false
	}
	if digitLen > 20 {
		return true
	}
	if neg {
		if digitLen < 19 {
			return false
		}
		if digitLen > 19 {
			return true
		}
		return num[start:] > "9223372036854775808"
	}
	if digitLen < 20 {
		return false
	}
	return num[start:] > "18446744073709551615"
}

func isDigit(c byte) bool {
	return c >= '0' && c <= '9'
}

// ponytail: borrowed strings never leave processLine; copy here if values escape.
func borrowedString(b []byte) string {
	if len(b) == 0 {
		return ""
	}
	return unsafe.String(unsafe.SliceData(b), len(b))
}

func borrowedBytes(s string) []byte {
	if len(s) == 0 {
		return nil
	}
	return unsafe.Slice(unsafe.StringData(s), len(s))
}

func main() {
	cpuProfile := flag.String("cpuprofile", "", "write CPU profile to file")
	flag.Parse()

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
	proc := processor{}
	for {
		line, err := reader.ReadBytes('\n')
		if err != nil && err != io.EOF {
			fmt.Fprintf(os.Stderr, "stdin read error: %v\n", err)
			os.Exit(1)
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

		if procErr := proc.processLine(line[:n], buf); procErr != nil {
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
