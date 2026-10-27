package main

import (
	"bufio"
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"runtime/pprof"
	"slices"
	"strings"
	"unsafe"
)

type normalizationKind byte

const (
	normalizationNone normalizationKind = iota
	normalizationStringArray
	normalizationObjectArray
	normalizationObject
)

type propertiesKind byte

const (
	eventProperties propertiesKind = iota
	personProperties
	temporaryProperties
	eventEnvelope
)

const (
	envelopeProperties = iota
	envelopeTemporaryProperties
	envelopePersonProperties
	envelopeDocs
)

type pathRule struct {
	normalization normalizationKind
	children      map[string]*pathRule
}

var eventPropertyRules = makeEventPropertyRules()

const (
	// Match fastjson's parser ceiling so every stored document remains readable by the blob-cleanup UDF.
	maxJSONDepth = 300
	// Nested arrays can amplify ClickHouse type inference even for small documents.
	maxJSONArrayDepth        = 8
	unparseablePropertiesKey = "$unparseable_properties"
	maxRecycledValues        = 4096
)

var errMaxJSONDepth = errors.New("maximum JSON depth exceeded")

func isDroppedEventProperty(key string) bool {
	switch key {
	case "$ai_input",
		"$ai_output",
		"$ai_output_choices",
		"$ai_input_state",
		"$ai_output_state",
		"$ai_tools",
		"ph_product_tours",
		"$product_tours_activated",
		"$product_tours_enabled_server_side",
		"$surveys_activated",
		"$active_feature_flags",
		"$feature_flag_payload",
		"$feature_flag_bootstrapped_payload",
		"$feature_flag_original_payload",
		"$feature_flag_payloads",
		"$transformations_succeeded",
		"$transformations_skipped",
		unparseablePropertiesKey:
		return true
	}
	return false
}

func isTemporaryProperty(key string) bool {
	if len(key) == 0 || key[0] != '$' {
		return false
	}
	switch key {
	case "$set", "$set_once", "$unset", "$group_set", "$feature_flag_request_id",
		"$debug_first_full_snapshot_timestamp", "$snapshot_max_depth_exceeded",
		"$sess_rec_flush_size", "$session_recording_remote_config",
		"$session_recording_network_payload_capture", "$session_recording_canvas_recording",
		"$replay_script_config", "$lib_rate_limit_remaining_tokens", "$lib_custom_api_host":
		return true
	case "$sdk_debug_current_session_duration":
		// Customers read it over windows longer than the temporary retention, so it stays permanent.
		return false
	}
	return strings.HasPrefix(key, "$sdk_debug_")
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
	addPathRules(root, normalizationObject, "$feature_flags")
	return root
}

// The typed map stores every flag value as a string, so a variant named "false" or "true" would read the same as a
// boolean flag that evaluated to JSON false or true. Such a variant is stored under its sentinel instead. The query
// layer maps the sentinels back to the variant names and the flag API refuses them as variant keys.
var variantSentinels = map[string]string{"false": "$false", "true": "$true"}

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

type processor struct {
	data          []byte
	pos           int
	kind          propertiesKind
	mutated       bool
	rawSafe       bool
	free          []*value
	info          map[string]entryInfo
	stringBuf     bytes.Buffer
	tooDeepArrays bool
	discard       bool
	collectNulls  bool
	nullFrames    []nullFrame
	nullKinds     map[string]valueKind
	docs          [envelopeDocs]bytes.Buffer
	nullDocs      [envelopeDocs]bytes.Buffer
}

// A container between the document root and the object being cleaned, with the node that collects the null
// fields recorded below it. The null document mirrors the input's shape, so a recorded null costs its own key
// and each container on the way to it once, however many nulls share that container. The node is created on
// the first null below the container, so a document without nulls allocates nothing for them.
type nullFrame struct {
	kind  valueKind
	key   string
	index int
	node  *value
}

func processLine(rawLine []byte, buf *bytes.Buffer) error {
	var proc processor
	return proc.processLine(rawLine, buf)
}

func (p *processor) processLine(rawLine []byte, buf *bytes.Buffer) error {
	if p.kind == eventEnvelope {
		return p.processEnvelopeLine(rawLine, buf)
	}
	p.prepareLine(rawLine, buf)
	return p.processDocument(rawLine, buf)
}

func (p *processor) prepareLine(rawLine []byte, buf *bytes.Buffer) {
	if buf.Cap() > max(64*1024, 2*len(rawLine)) {
		*buf = bytes.Buffer{}
	}
	if p.stringBuf.Cap() > max(64*1024, 2*len(rawLine)) {
		p.stringBuf = bytes.Buffer{}
	}
	p.resetParser(rawLine)
}

func (p *processor) resetParser(data []byte) {
	p.data = data
	p.pos = 0
	p.mutated = false
	p.rawSafe = true
	p.tooDeepArrays = false
}

// A nil value with a nil error means the document is too deep or nests arrays too deeply; the caller quarantines it.
func (p *processor) parseDocument(raw []byte) (*value, error) {
	p.resetParser(raw)
	parsed, err := p.parseValue(1, 0)
	if err != nil {
		if errors.Is(err, errMaxJSONDepth) {
			return nil, nil
		}
		return nil, fmt.Errorf("json parse error: %w", err)
	}
	p.skipWS()
	if p.pos != len(p.data) {
		p.recycle(parsed)
		return nil, fmt.Errorf("json parse error: trailing data at byte %d", p.pos)
	}
	// Parsing counts arrays inside discarded properties so quarantine preserves rejected inputs.
	if p.tooDeepArrays {
		p.recycle(parsed)
		return nil, nil
	}
	return parsed, nil
}

func (p *processor) processDocument(rawLine []byte, buf *bytes.Buffer) error {
	parsed, err := p.parseDocument(rawLine)
	if err != nil {
		return err
	}
	if parsed == nil {
		p.writeUnparseableProperties(buf, rawLine)
		return nil
	}

	cleaned, err := p.cleanProperties(parsed)
	if err != nil {
		p.recycle(parsed)
		if errors.Is(err, errMaxJSONDepth) {
			p.writeUnparseableProperties(buf, rawLine)
			return nil
		}
		return fmt.Errorf("json clean error: %w", err)
	}
	// Normalization can decode stringified JSON and wrap objects in arrays.
	if p.mutated && exceedsJSONArrayDepth(cleaned, 0) {
		p.recycle(cleaned)
		p.writeUnparseableProperties(buf, rawLine)
		return nil
	}

	buf.Reset()
	if !p.mutated && p.rawSafe {
		buf.Write(rawLine)
	} else {
		p.writeValue(buf, cleaned)
	}
	p.recycle(cleaned)
	return nil
}

func exceedsJSONArrayDepth(v *value, depth int) bool {
	if v.kind == kindArray {
		depth++
		if depth > maxJSONArrayDepth {
			return true
		}
		for _, child := range v.values {
			if exceedsJSONArrayDepth(child, depth) {
				return true
			}
		}
	} else if v.kind == kindObject {
		for _, entry := range v.entries {
			if exceedsJSONArrayDepth(entry.value, depth) {
				return true
			}
		}
	}
	return false
}

func (p *processor) cleanProperties(v *value) (*value, error) {
	if p.kind == temporaryProperties {
		return p.cleanTemporaryProperties(v)
	}
	if p.kind == personProperties {
		return p.cleanNode(nil, v, 1)
	}
	return p.cleanEventProperties(v)
}

func (p *processor) cleanTemporaryProperties(v *value) (*value, error) {
	if v.kind != kindObject {
		return nil, fmt.Errorf("temporary properties must be a JSON object")
	}
	return p.cleanNode(nil, v, 1)
}

func (p *processor) cleanEventProperties(v *value) (*value, error) {
	if v.kind != kindObject {
		return p.cleanNode(eventPropertyRules, v, 1)
	}

	var featureFlags *value
	hasFeatureProperties := false
	hasFeatureKeys := false
	for _, property := range v.entries {
		if !strings.HasPrefix(property.key, "$feature") {
			continue
		}
		hasFeatureKeys = true
		if strings.HasPrefix(property.key, "$feature/") {
			hasFeatureProperties = true
		} else if property.key == "$feature_flags" && property.value.kind == kindObject && featureFlags == nil {
			featureFlags = property.value
		}
	}
	if !hasFeatureKeys {
		return p.cleanNode(eventPropertyRules, v, 1)
	}
	createdFeatureFlags := hasFeatureProperties && featureFlags == nil
	if createdFeatureFlags {
		featureFlags = p.newValue(kindObject)
	}

	writeIdx := 0
	for _, property := range v.entries {
		if hasFeatureProperties && property.key == "$feature_flags" && property.value != featureFlags {
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
	cleaned, err := p.cleanNode(eventPropertyRules, v, 1)
	if err != nil {
		return nil, err
	}
	for _, property := range cleaned.entries {
		if property.key == "$feature_flags" && property.value.kind == kindObject {
			for _, flag := range property.value.entries {
				if sentinel, ok := variantSentinels[flag.value.s]; ok && flag.value.kind == kindString {
					flag.value.s = sentinel
					p.mutated = true
				}
			}
			compare := func(a, b entry) int { return strings.Compare(a.key, b.key) }
			if !slices.IsSortedFunc(property.value.entries, compare) {
				slices.SortFunc(property.value.entries, compare)
				p.mutated = true
			}
		}
	}
	return cleaned, nil
}

func (p *processor) newValue(kind valueKind) *value {
	if p.discard {
		return nil
	}
	n := len(p.free)
	if n == 0 {
		return &value{kind: kind}
	}
	v := p.free[n-1]
	p.free[n-1] = nil
	p.free = p.free[:n-1]
	v.kind = kind
	return v
}

func (p *processor) recycle(v *value) {
	if v == nil {
		return
	}
	if v.kind < kindObject && cap(v.entries) <= 16 && cap(v.values) <= 16 {
		if len(p.free) < maxRecycledValues {
			v.s = ""
			v.b = false
			p.free = append(p.free, v)
		}
		return
	}
	for _, entry := range v.entries {
		p.recycle(entry.value)
	}
	for _, child := range v.values {
		p.recycle(child)
	}
	// A single large retained property must not pin its entire tree in an executable pool worker.
	if len(p.free) >= maxRecycledValues {
		return
	}
	v.s = ""
	v.b = false
	// Keep small arrays for reuse; bound clearing work for larger ones by this row's size.
	if cap(v.entries) > max(16, 2*len(v.entries)) {
		v.entries = nil
	}
	if cap(v.values) > max(16, 2*len(v.values)) {
		v.values = nil
	}
	// Truncated entries can still hold borrowed keys that retain entire input rows.
	if v.kind == kindObject {
		clear(v.entries[:cap(v.entries)])
	} else if v.kind == kindArray {
		clear(v.values[:cap(v.values)])
	}
	v.entries = v.entries[:0]
	v.values = v.values[:0]
	p.free = append(p.free, v)
}

func (p *processor) parseValue(depth, arrayDepth int) (*value, error) {
	if depth > maxJSONDepth {
		return nil, errMaxJSONDepth
	}

	p.skipWS()
	if p.pos >= len(p.data) {
		return nil, fmt.Errorf("unexpected end of input")
	}

	switch p.data[p.pos] {
	case '{':
		return p.parseObject(depth, arrayDepth)
	case '[':
		return p.parseArray(depth, arrayDepth)
	case '"':
		s, err := p.parseString()
		if err != nil {
			return nil, err
		}
		v := p.newValue(kindString)
		if v != nil {
			v.s = s
		}
		return v, nil
	case 't':
		if !p.consumeLiteral("true") {
			return nil, fmt.Errorf("invalid literal at byte %d", p.pos)
		}
		v := p.newValue(kindBool)
		if v != nil {
			v.b = true
		}
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
			if v == nil {
				return nil, nil
			}
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

func (p *processor) parseObject(depth, arrayDepth int) (*value, error) {
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
		discard := p.discard
		if depth == 1 {
			switch p.kind {
			case eventProperties:
				p.discard = isDroppedEventProperty(key) || isTemporaryProperty(key)
			case temporaryProperties:
				p.discard = !isTemporaryProperty(key)
			case eventEnvelope:
				// Temporary properties are split off after parsing, so only the drop list is discarded here.
				p.discard = isDroppedEventProperty(key)
			}
			p.mutated = p.mutated || p.discard
		}
		// Discarded properties still pass the same syntax and depth validation.
		child, err := p.parseValue(depth+1, arrayDepth)
		p.discard = discard
		if err != nil {
			p.recycle(obj)
			return nil, err
		}
		if obj != nil && child != nil {
			obj.entries = append(obj.entries, entry{key: key, value: child})
		}
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

func (p *processor) parseArray(depth, arrayDepth int) (*value, error) {
	arrayDepth++
	if arrayDepth > maxJSONArrayDepth {
		p.tooDeepArrays = true
	}
	p.pos++
	arr := p.newValue(kindArray)
	p.skipWS()
	if p.consumeByte(']') {
		return arr, nil
	}

	for {
		child, err := p.parseValue(depth+1, arrayDepth)
		if err != nil {
			p.recycle(arr)
			return nil, err
		}
		if arr != nil {
			arr.values = append(arr.values, child)
		}
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

var stringSpecialBytes = func() (special [256]bool) {
	for i := range 0x20 {
		special[i] = true
	}
	special['"'], special['\\'] = true, true
	return
}()

func (p *processor) parseString() (string, error) {
	quote := p.pos
	start := quote + 1
	for i, c := range p.data[start:] {
		if !stringSpecialBytes[c] {
			continue
		}
		switch {
		case c == '"':
			s := borrowedString(p.data[start : start+i])
			p.pos = start + i + 1
			return s, nil
		case c == '\\':
			p.pos = start + i
			return p.parseEscapedString(quote)
		case c < 0x20:
			return "", fmt.Errorf("invalid control character at byte %d", start+i)
		}
	}
	return "", fmt.Errorf("unterminated string at byte %d", quote)
}

func (p *processor) parseEscapedString(quote int) (string, error) {
	p.stringBuf.Reset()
	if !p.discard {
		p.stringBuf.Write(p.data[quote+1 : p.pos])
	}
	for p.pos < len(p.data) {
		start := p.pos
		p.pos = len(p.data)
		for i, c := range p.data[start:] {
			if stringSpecialBytes[c] {
				p.pos = start + i
				break
			}
		}
		if !p.discard {
			p.stringBuf.Write(p.data[start:p.pos])
		}
		if p.pos == len(p.data) {
			break
		}
		switch p.data[p.pos] {
		case '"':
			p.pos++
			return p.stringBuf.String(), nil
		case '\\':
			p.pos++
			if p.pos >= len(p.data) {
				return "", fmt.Errorf("unterminated escape at byte %d", p.pos)
			}
			var decoded byte
			switch p.data[p.pos] {
			case '"', '\\', '/':
				decoded = p.data[p.pos]
				if decoded == '/' {
					p.rawSafe = false
				}
			case 'b':
				decoded = '\b'
			case 'f':
				decoded = '\f'
			case 'n':
				decoded = '\n'
			case 'r':
				decoded = '\r'
			case 't':
				decoded = '\t'
			case 'u':
				p.rawSafe = false
				r, err := p.parseUnicodeEscape()
				if err != nil {
					return "", err
				}
				if !p.discard {
					p.stringBuf.WriteRune(r)
				}
				continue
			default:
				return "", fmt.Errorf("invalid escape at byte %d", p.pos)
			}
			if !p.discard {
				p.stringBuf.WriteByte(decoded)
			}
			p.pos++
		default:
			return "", fmt.Errorf("invalid control character at byte %d", p.pos)
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
	start, pos := p.pos, p.pos
	if pos < len(p.data) && p.data[pos] == '-' {
		pos++
	}
	if pos >= len(p.data) {
		return "", fmt.Errorf("short number at byte %d", start)
	}

	if p.data[pos] == '0' {
		pos++
	} else if p.data[pos] >= '1' && p.data[pos] <= '9' {
		for pos < len(p.data) && isDigit(p.data[pos]) {
			pos++
		}
	} else {
		return "", fmt.Errorf("invalid number at byte %d", start)
	}

	if pos < len(p.data) && p.data[pos] == '.' {
		pos++
		if pos >= len(p.data) || !isDigit(p.data[pos]) {
			return "", fmt.Errorf("invalid fraction at byte %d", pos)
		}
		for pos < len(p.data) && isDigit(p.data[pos]) {
			pos++
		}
	}

	if pos < len(p.data) && (p.data[pos] == 'e' || p.data[pos] == 'E') {
		pos++
		if pos < len(p.data) && (p.data[pos] == '+' || p.data[pos] == '-') {
			pos++
		}
		if pos >= len(p.data) || !isDigit(p.data[pos]) {
			return "", fmt.Errorf("invalid exponent at byte %d", pos)
		}
		for pos < len(p.data) && isDigit(p.data[pos]) {
			pos++
		}
	}

	p.pos = pos
	return borrowedString(p.data[start:pos]), nil
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

func (p *processor) cleanNode(pathRules *pathRule, v *value, depth int) (*value, error) {
	// Scalar children skip recursion, but must still fit below their container's depth.
	if depth > maxJSONDepth || depth == maxJSONDepth && (len(v.entries) != 0 || len(v.values) != 0) {
		return nil, errMaxJSONDepth
	}

	switch v.kind {
	case kindObject:
		if err := p.cleanObject(pathRules, v, depth); err != nil {
			return nil, err
		}
	case kindArray:
		for i, child := range v.values {
			if child.kind < kindObject {
				continue
			}
			if p.collectNulls {
				p.pushNullFrame(child.kind, "", i)
			}
			cleaned, err := p.cleanNode(pathRules, child, depth+1)
			if err != nil {
				return nil, err
			}
			if p.collectNulls {
				p.popNullFrame(true)
			}
			v.values[i] = cleaned
		}
	}
	return v, nil
}

func (p *processor) cleanObject(pathRules *pathRule, obj *value, depth int) error {
	var err error
	var unparsable bytes.Buffer
	writeIdx := 0
	for readIdx, entry := range obj.entries {
		var childPathRules *pathRule
		if pathRules != nil {
			childPathRules = pathRules.children[entry.key]
		}
		cleaned := entry.value
		// Normalization can reset the value in place, so remember whether a frame was pushed for it.
		pushedNullFrame := p.collectNulls && cleaned.kind >= kindObject
		keepNulls := true
		if cleaned.kind >= kindObject {
			if pushedNullFrame {
				p.pushNullFrame(cleaned.kind, entry.key, 0)
			}
			cleaned, err = p.cleanNode(childPathRules, cleaned, depth+1)
			if err != nil {
				p.retainUnprocessedEntries(obj, writeIdx, readIdx)
				return err
			}
		}
		if childPathRules != nil && childPathRules.normalization != normalizationNone {
			p.mutated = true
			original := cleaned
			cleaned, err = p.normalizeValue(childPathRules.normalization, cleaned, depth)
			// Nulls recorded below the child describe its shape before normalization. A wrapped object, a
			// quarantined value or an array coerced to strings no longer has that shape.
			keepNulls = err == nil && cleaned == original && childPathRules.normalization != normalizationStringArray
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
				if childPathRules.normalization == normalizationObject {
					p.resetValue(cleaned, kindObject)
				} else {
					cleaned = p.reuseAsEmptyArray(cleaned)
				}
			}
		}
		if pushedNullFrame {
			p.popNullFrame(keepNulls)
		}
		if cleaned.kind == kindNull {
			p.mutated = true
			if p.collectNulls {
				p.recordNull(entry.key)
			}
			p.recycle(cleaned)
			continue
		}
		if writeIdx != readIdx || cleaned != entry.value {
			obj.entries[writeIdx] = entry
			obj.entries[writeIdx].value = cleaned
		}
		writeIdx++
	}
	obj.entries = obj.entries[:writeIdx]
	if unparsable.Len() > 0 {
		unparsable.WriteByte('}')
		marker := p.newValue(kindString)
		marker.s = unparsable.String()
		obj.entries = append(obj.entries, entry{key: unparseablePropertiesKey, value: marker})
	}
	p.deduplicateEntries(obj)
	if p.collectNulls {
		p.pruneNullEntries(obj)
	}
	return nil
}

func (p *processor) retainUnprocessedEntries(obj *value, writeIdx, readIdx int) {
	remaining := len(obj.entries) - readIdx
	copy(obj.entries[writeIdx:writeIdx+remaining], obj.entries[readIdx:])
	obj.entries = obj.entries[:writeIdx+remaining]
}

func (p *processor) writeUnparseableProperties(buf *bytes.Buffer, raw []byte) {
	buf.Reset()
	if p.kind == temporaryProperties {
		// The permanent cleaner quarantines the raw document; do not duplicate it outside the allowlist.
		buf.WriteString("{}")
		return
	}
	buf.Grow(len(raw) + len(unparseablePropertiesKey) + 8)
	buf.WriteByte('{')
	writeJSONString(buf, unparseablePropertiesKey)
	buf.WriteByte(':')
	writeJSONString(buf, borrowedString(raw))
	buf.WriteByte('}')
}

func (p *processor) deduplicateEntries(obj *value) {
	if len(obj.entries) < 2 {
		return
	}
	// Bound pairwise comparisons to small objects; wide objects use the hash table.
	if len(obj.entries) <= 16 {
		duplicate := false
		for i, entry := range obj.entries {
			for _, previous := range obj.entries[:i] {
				if previous.key == entry.key {
					duplicate = true
					break
				}
			}
			if duplicate {
				break
			}
		}
		if !duplicate {
			return
		}
	}
	if p.info == nil {
		p.info = make(map[string]entryInfo, len(obj.entries))
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
			if writeIdx != i {
				obj.entries[writeIdx] = entry
			}
			writeIdx++
		} else {
			p.mutated = true
			p.recycle(entry.value)
		}
	}
	obj.entries = obj.entries[:writeIdx]

	if len(p.info) > maxRecycledValues {
		p.info = nil
	} else {
		clear(p.info)
	}
}

func (p *processor) normalizeValue(normalization normalizationKind, v *value, depth int) (*value, error) {
	switch normalization {
	case normalizationStringArray:
		return p.coerceStringArray(v, depth)
	case normalizationObjectArray:
		return p.coerceObjectArray(v, depth)
	case normalizationObject:
		if v.kind != kindObject && v.kind != kindNull {
			return nil, fmt.Errorf("cannot coerce %s to Map", valueKindName(v.kind))
		}
		return v, nil
	default:
		return v, nil
	}
}

func (p *processor) coerceObjectArray(v *value, depth int) (*value, error) {
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
		parsed, err := p.parseStringifiedJSON(raw, depth)
		if err != nil {
			return nil, err
		}
		normalized, err := p.coerceObjectArray(parsed, depth)
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

func (p *processor) coerceStringArray(v *value, depth int) (*value, error) {
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
		if parsed, ok, err := p.parseStringifiedJSONArray(trimmed, depth); err != nil {
			return nil, err
		} else if ok {
			p.recycle(v)
			return p.coerceStringArray(parsed, depth)
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
	clear(v.entries[:cap(v.entries)])
	clear(v.values[:cap(v.values)])
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

func (p *processor) parseStringifiedJSON(raw string, depth int) (*value, error) {
	if raw == "" || (raw[0] != '[' && raw[0] != '{') {
		return nil, fmt.Errorf("cannot coerce %q to Array(JSON)", raw)
	}

	oldData, oldPos := p.data, p.pos
	p.data = borrowedBytes(raw)
	p.pos = 0
	parsed, err := p.parseValue(depth+1, 0)
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
	cleaned, err := p.cleanNode(nil, parsed, depth+1)
	p.data, p.pos = oldData, oldPos
	if err != nil {
		p.recycle(parsed)
		return nil, err
	}
	return cleaned, nil
}

func (p *processor) parseStringifiedJSONArray(raw string, depth int) (*value, bool, error) {
	if raw == "" || raw[0] != '[' {
		return nil, false, nil
	}

	oldData, oldPos := p.data, p.pos
	p.data = borrowedBytes(raw)
	p.pos = 0
	parsed, err := p.parseValue(depth+1, 0)
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
	cleaned, err := p.cleanNode(nil, parsed, depth+1)
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
	if len(num) < 19 {
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
	// nosemgrep: go.lang.security.audit.unsafe.use-of-unsafe-block -- b owns the bytes for every use of the borrowed string.
	return unsafe.String(unsafe.SliceData(b), len(b))
}

func borrowedBytes(s string) []byte {
	if len(s) == 0 {
		return nil
	}
	// nosemgrep: go.lang.security.audit.unsafe.use-of-unsafe-block -- callers only read the slice while s remains live.
	return unsafe.Slice(unsafe.StringData(s), len(s))
}

// Envelope rows arrive as JSONEachRow, {"properties": "<json>", "person_properties": "<json>"}, and go back as
// {"result": {...}} matching the named tuple declared for JSONCleanPostHogEvent.

const (
	envelopePropertiesField       = "properties"
	envelopePersonPropertiesField = "person_properties"
)

var envelopeDocNames = [envelopeDocs]string{
	envelopeProperties:          "properties",
	envelopeTemporaryProperties: "temporary_properties",
	envelopePersonProperties:    "person_properties",
}

func (p *processor) processEnvelopeLine(rawLine []byte, buf *bytes.Buffer) error {
	p.prepareLine(rawLine, buf)

	// The outer row is trusted ClickHouse output, so a parse failure is a protocol error.
	p.kind = personProperties
	outer, err := p.parseDocument(rawLine)
	p.kind = eventEnvelope
	if err != nil {
		return fmt.Errorf("envelope row: %w", err)
	}
	if outer == nil || outer.kind != kindObject {
		p.recycle(outer)
		return fmt.Errorf("envelope row: expected a JSON object")
	}
	var properties, personProperties string
	for _, field := range outer.entries {
		if field.value.kind != kindString {
			continue
		}
		switch field.key {
		case envelopePropertiesField:
			properties = field.value.s
		case envelopePersonPropertiesField:
			personProperties = field.value.s
		}
	}
	// Escaped strings were copied out of stringBuf; unescaped ones borrow rawLine, which outlives this call.
	p.recycle(outer)

	p.cleanEventDocument(borrowedBytes(properties))
	p.cleanPersonDocument(borrowedBytes(personProperties))

	buf.Reset()
	buf.WriteString(`{"result":{`)
	for i, name := range envelopeDocNames {
		if i > 0 {
			buf.WriteByte(',')
		}
		writeJSONString(buf, name)
		buf.WriteByte(':')
		writeJSONString(buf, borrowedString(p.docs[i].Bytes()))
	}
	for i, name := range envelopeDocNames {
		buf.WriteString(`,"`)
		buf.WriteString(name)
		buf.WriteString(`_nulls":`)
		writeJSONString(buf, borrowedString(p.nullDocs[i].Bytes()))
	}
	buf.WriteString("}}")
	return nil
}

func (p *processor) cleanEventDocument(raw []byte) {
	permanent := &p.docs[envelopeProperties]
	temporary := &p.docs[envelopeTemporaryProperties]
	permanent.Reset()
	temporary.Reset()
	p.nullDocs[envelopeProperties].Reset()
	p.nullDocs[envelopeTemporaryProperties].Reset()

	if isBlank(raw) {
		permanent.WriteString("{}")
		temporary.WriteString("{}")
		return
	}
	quarantine := func() {
		p.writeUnparseableProperties(permanent, raw)
		temporary.Reset()
		temporary.WriteString("{}")
	}

	parsed, err := p.parseDocument(raw)
	if err != nil || parsed == nil || parsed.kind != kindObject {
		p.recycle(parsed)
		quarantine()
		return
	}

	// Split the temporary allowlist off the top level; the drop list was discarded while parsing.
	temporaryObject := p.newValue(kindObject)
	writeIdx := 0
	for _, property := range parsed.entries {
		if isTemporaryProperty(property.key) {
			temporaryObject.entries = append(temporaryObject.entries, property)
			continue
		}
		parsed.entries[writeIdx] = property
		writeIdx++
	}
	clear(parsed.entries[writeIdx:])
	parsed.entries = parsed.entries[:writeIdx]

	p.collectNulls = true
	defer func() { p.collectNulls = false }()

	p.beginNullDocument()
	cleaned, err := p.cleanEventProperties(parsed)
	if err != nil || (p.mutated && exceedsJSONArrayDepth(cleaned, 0)) {
		if err != nil {
			p.recycle(parsed)
		} else {
			p.recycle(cleaned)
		}
		p.recycle(temporaryObject)
		p.discardNullDocument()
		quarantine()
		return
	}
	p.finishNullDocument(&p.nullDocs[envelopeProperties])
	p.writeValue(permanent, cleaned)
	p.recycle(cleaned)

	p.beginNullDocument()
	cleanedTemporary, err := p.cleanNode(nil, temporaryObject, 1)
	if err != nil || (p.mutated && exceedsJSONArrayDepth(cleanedTemporary, 0)) {
		// The permanent output already quarantines the raw document; do not duplicate it outside the allowlist.
		if err != nil {
			p.recycle(temporaryObject)
		} else {
			p.recycle(cleanedTemporary)
		}
		p.discardNullDocument()
		temporary.WriteString("{}")
		return
	}
	p.finishNullDocument(&p.nullDocs[envelopeTemporaryProperties])
	p.writeValue(temporary, cleanedTemporary)
	p.recycle(cleanedTemporary)
}

func (p *processor) cleanPersonDocument(raw []byte) {
	out := &p.docs[envelopePersonProperties]
	out.Reset()
	p.nullDocs[envelopePersonProperties].Reset()

	if isBlank(raw) {
		out.WriteString("{}")
		return
	}
	p.kind = personProperties
	parsed, err := p.parseDocument(raw)
	p.kind = eventEnvelope
	if err != nil || parsed == nil || parsed.kind != kindObject {
		p.recycle(parsed)
		p.writeUnparseableProperties(out, raw)
		return
	}

	p.collectNulls = true
	defer func() { p.collectNulls = false }()

	p.beginNullDocument()
	cleaned, err := p.cleanNode(nil, parsed, 1)
	if err != nil || (p.mutated && exceedsJSONArrayDepth(cleaned, 0)) {
		if err != nil {
			p.recycle(parsed)
		} else {
			p.recycle(cleaned)
		}
		p.discardNullDocument()
		p.writeUnparseableProperties(out, raw)
		return
	}
	p.finishNullDocument(&p.nullDocs[envelopePersonProperties])
	p.writeValue(out, cleaned)
	p.recycle(cleaned)
}

func isBlank(raw []byte) bool {
	for _, c := range raw {
		if c != ' ' && c != '\t' && c != '\n' && c != '\r' {
			return false
		}
	}
	return true
}

func (p *processor) beginNullDocument() {
	p.nullFrames = append(p.nullFrames[:0], nullFrame{kind: kindObject})
}

func (p *processor) pushNullFrame(kind valueKind, key string, index int) {
	p.nullFrames = append(p.nullFrames, nullFrame{kind: kind, key: key, index: index})
}

func (p *processor) ensureNullNode(i int) *value {
	if node := p.nullFrames[i].node; node != nil {
		return node
	}
	frame := p.nullFrames[i]
	node := p.newValue(frame.kind)
	p.nullFrames[i].node = node
	if i == 0 {
		return node
	}
	parent := p.ensureNullNode(i - 1)
	if parent.kind == kindArray {
		// An array keeps its positions: each earlier element with nothing to restore is an empty object.
		for len(parent.values) < frame.index {
			parent.values = append(parent.values, p.newValue(kindObject))
		}
		parent.values = append(parent.values, node)
	} else {
		parent.entries = append(parent.entries, entry{key: frame.key, value: node})
	}
	return node
}

func (p *processor) recordNull(key string) {
	node := p.ensureNullNode(len(p.nullFrames) - 1)
	node.entries = append(node.entries, entry{key: key, value: p.newValue(kindNull)})
}

// A node that comes off is the last child of its parent, because only its own descendants ran since it was
// attached, so no search is needed, and the placeholders that only led to it come off with it.
func (p *processor) popNullFrame(keep bool) {
	last := len(p.nullFrames) - 1
	node := p.nullFrames[last].node
	p.nullFrames[last] = nullFrame{}
	p.nullFrames = p.nullFrames[:last]
	if node == nil || keep && (len(node.entries) > 0 || len(node.values) > 0) {
		return
	}
	parent := p.nullFrames[last-1].node
	if parent.kind == kindArray {
		parent.values = parent.values[:len(parent.values)-1]
		for n := len(parent.values); n > 0 && parent.values[n-1].kind == kindObject && len(parent.values[n-1].entries) == 0; n-- {
			p.recycle(parent.values[n-1])
			parent.values = parent.values[:n-1]
		}
	} else {
		parent.entries = parent.entries[:len(parent.entries)-1]
	}
	p.recycle(node)
}

// A duplicate key can keep a value under a recorded null, record the same null twice, or replace a
// container that recorded nulls below it with a value of another kind. A null stays only where no value
// survived, once per key, and a child node only where its container kept its kind.
func (p *processor) pruneNullEntries(obj *value) {
	node := p.nullFrames[len(p.nullFrames)-1].node
	if node == nil {
		return
	}
	if p.nullKinds == nil {
		p.nullKinds = make(map[string]valueKind, len(obj.entries))
	}
	for _, survivor := range obj.entries {
		p.nullKinds[survivor.key] = survivor.value.kind
	}
	writeIdx := 0
	for _, recorded := range node.entries {
		kind, found := p.nullKinds[recorded.key]
		var keep bool
		if recorded.value.kind == kindNull {
			keep = !found
			if keep {
				p.nullKinds[recorded.key] = kindNull
			}
		} else {
			keep = found && kind == recorded.value.kind
		}
		if keep {
			node.entries[writeIdx] = recorded
			writeIdx++
		} else {
			p.recycle(recorded.value)
		}
	}
	clear(node.entries[writeIdx:])
	node.entries = node.entries[:writeIdx]
	// A pooled worker reuses the processor across rows, so drop a large map instead of keeping its memory.
	if len(p.nullKinds) > maxRecycledValues {
		p.nullKinds = nil
	} else {
		clear(p.nullKinds)
	}
}

func (p *processor) finishNullDocument(out *bytes.Buffer) {
	root := p.nullFrames[0].node
	p.resetNullFrames()
	if root == nil {
		return
	}
	if len(root.entries) > 0 {
		p.writeValue(out, root)
	}
	p.recycle(root)
}

// Every node is attached under the root when it is created, so recycling the root releases the whole tree.
func (p *processor) discardNullDocument() {
	root := p.nullFrames[0].node
	p.resetNullFrames()
	p.recycle(root)
}

// Frame keys borrow the input row, so the backing array is cleared before the pool worker reads the next row.
func (p *processor) resetNullFrames() {
	clear(p.nullFrames[:cap(p.nullFrames)])
	p.nullFrames = p.nullFrames[:0]
}

func readLine(reader *bufio.Reader) ([]byte, error) {
	line, err := reader.ReadSlice('\n')
	if err != bufio.ErrBufferFull {
		return line, err
	}
	// Only rows larger than the reader buffer need an owned copy.
	var full []byte
	for {
		full = append(full, line...)
		if err != bufio.ErrBufferFull {
			return full, err
		}
		line, err = reader.ReadSlice('\n')
	}
}

func run(input io.Reader, output io.Writer, kind propertiesKind) error {
	reader := bufio.NewReaderSize(input, 64*1024)
	writer := bufio.NewWriterSize(output, 64*1024)
	buf := bytes.NewBuffer(make([]byte, 0, 64*1024))
	proc := processor{kind: kind}

	for {
		line, err := readLine(reader)
		if err != nil && err != io.EOF {
			return fmt.Errorf("stdin read error: %w", err)
		}
		if len(line) == 0 && err == io.EOF {
			return writer.Flush()
		}

		hadNewline := len(line) > 0 && line[len(line)-1] == '\n'
		line = bytes.TrimSuffix(line, []byte{'\n'})
		line = bytes.TrimSuffix(line, []byte{'\r'})
		if processErr := proc.processLine(line, buf); processErr != nil {
			return fmt.Errorf("line processing error: %w", processErr)
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

func runChunked(input io.Reader, output io.Writer, kind propertiesKind) error {
	reader := bufio.NewReaderSize(input, 64*1024)
	writer := bufio.NewWriterSize(output, 64*1024)
	buf := bytes.NewBuffer(make([]byte, 0, 64*1024))
	proc := processor{kind: kind}

	for {
		var rows int
		if _, err := fmt.Fscanln(reader, &rows); err == io.EOF {
			return writer.Flush()
		} else if err != nil {
			return fmt.Errorf("chunk header read error: %w", err)
		}
		for range rows {
			line, err := readLine(reader)
			if err != nil {
				return fmt.Errorf("stdin read error: %w", err)
			}
			line = bytes.TrimSuffix(line, []byte{'\n'})
			line = bytes.TrimSuffix(line, []byte{'\r'})
			if processErr := proc.processLine(line, buf); processErr != nil {
				return fmt.Errorf("line processing error: %w", processErr)
			}
			if _, writeErr := writer.Write(buf.Bytes()); writeErr != nil {
				return fmt.Errorf("stdout write error: %w", writeErr)
			}
			if writeErr := writer.WriteByte('\n'); writeErr != nil {
				return fmt.Errorf("stdout write error: %w", writeErr)
			}
		}
		if err := writer.Flush(); err != nil {
			return fmt.Errorf("stdout flush error: %w", err)
		}
	}
}

func main() {
	cpuProfile := flag.String("cpuprofile", "", "write CPU profile to file")
	chunked := flag.Bool("chunked", false, "read a row-count header before each input chunk")
	cleanPersonProperties := flag.Bool("person-properties", false, "clean person properties without event-specific transformations")
	cleanTemporaryProperties := flag.Bool("temporary-properties", false, "retain only temporary event properties")
	envelope := flag.Bool("event", false, "read JSONEachRow rows of event and person properties and write a JSONEachRow named tuple with every cleaned output")
	flag.Parse()
	modes := 0
	for _, enabled := range []bool{*cleanPersonProperties, *cleanTemporaryProperties, *envelope} {
		if enabled {
			modes++
		}
	}
	if modes > 1 {
		fmt.Fprintln(os.Stderr, "person-properties, temporary-properties and event are mutually exclusive")
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

	runner := run
	if *chunked {
		runner = runChunked
	}
	kind := eventProperties
	if *cleanPersonProperties {
		kind = personProperties
	}
	if *cleanTemporaryProperties {
		kind = temporaryProperties
	}
	if *envelope {
		kind = eventEnvelope
	}
	if err := runner(os.Stdin, os.Stdout, kind); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
