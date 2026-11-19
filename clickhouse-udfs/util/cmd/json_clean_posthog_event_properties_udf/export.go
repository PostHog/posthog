package main

import (
	"bytes"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Export mode writes each envelope document as the JSON value that a read of the native JSON events columns returns,
// so a table filled from this mode holds what a batch export of the events table sends. That read is the cleaner's
// output, cast into the JSON column type, then printed by the document builder in
// posthog/hogql/printer/events_json_document.py. The rules in this file are the behavior of that cast and of that
// builder. A change to either one needs the matching change here.

const (
	// The parser behind ClickHouse's isValidJSON refuses a value below this many levels. A scalar counts as a level.
	maxValidJSONDepth = 1024
	// The largest Float64 has 309 digits before the decimal point, so a shorter number with no exponent fits.
	minFloat64OverflowLength = 309
	// ClickHouse prints a Float64 in positional notation when its decimal exponent is in this range, and with an
	// exponent outside it.
	minPositionalExponent = -6
	maxPositionalExponent = 21
	// shouldStringifyNumber returns false for every shorter integer.
	minStringifiedIntegerLength = 19
	// How json_type_escape_dots_in_keys spells a dot inside one key. A read turns it back into a dot, so a key sent
	// with this text comes back with a dot too.
	escapedDot = "%2E"
)

// The paths the events table declares as String or LowCardinality(String), from
// EVENTS_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES in posthog/clickhouse/events_json.py. Update both together.
func isDeclaredEventStringPath(key string) bool {
	if len(key) == 0 || key[0] != '$' {
		return false
	}
	switch key {
	case "$browser", "$browser_language", "$browser_version", "$config_defaults", "$current_url", "$device_type",
		"$geoip_city_name", "$geoip_continent_code", "$geoip_continent_name", "$geoip_country_code",
		"$geoip_country_name", "$geoip_subdivision_1_name", "$geoip_time_zone",
		"$group_0", "$group_1", "$group_2", "$group_3", "$group_4",
		"$host", "$lib", "$lib_version", "$os", "$os_version", "$pathname", "$session_id", "$timezone", "$window_id":
		return true
	}
	return false
}

// The same for person properties, from PERSON_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES.
func isDeclaredPersonStringPath(key string) bool {
	if len(key) == 0 || key[0] != '$' {
		return false
	}
	switch key {
	case "$browser", "$browser_language", "$browser_version", "$device_type",
		"$geoip_city_name", "$geoip_continent_code", "$geoip_continent_name", "$geoip_country_code",
		"$geoip_country_name", "$geoip_subdivision_1_name", "$geoip_time_zone",
		"$initial_browser", "$initial_browser_language", "$initial_browser_version", "$initial_device_type",
		"$initial_geoip_city_name", "$initial_geoip_continent_code", "$initial_geoip_continent_name",
		"$initial_geoip_country_code", "$initial_geoip_country_name", "$initial_geoip_subdivision_1_name",
		"$initial_geoip_time_zone", "$initial_os", "$initial_os_version", "$os", "$os_version":
		return true
	}
	return false
}

func isFloatToken(num string) bool {
	for i := 0; i < len(num); i++ {
		switch num[i] {
		case '.', 'e', 'E':
			return true
		}
	}
	return false
}

// ClickHouse refuses a number with a fraction or an exponent that is outside the Float64 range. It accepts an
// integer of any length.
func overflowsFloat64(num string) bool {
	if len(num) < minFloat64OverflowLength && !strings.ContainsAny(num, "eE") {
		return false
	}
	if !isFloatToken(num) {
		return false
	}
	f, _ := strconv.ParseFloat(num, 64)
	return math.IsInf(f, 0)
}

// appendClickHouseNumber appends the text the JSON column stores when it reads the JSON number num into a String
// path. It keeps an integer as written. It reads a number with a fraction or an exponent as a Float64 and prints the
// shortest text that reads back to the same value. The caller has checked that num fits a Float64.
func appendClickHouseNumber(dst []byte, num string) []byte {
	if !isFloatToken(num) {
		if num == "-0" {
			return append(dst, '0')
		}
		return append(dst, num...)
	}
	f, _ := strconv.ParseFloat(num, 64)
	if f == 0 {
		if math.Signbit(f) {
			dst = append(dst, '-')
		}
		return append(dst, '0')
	}
	if f < 0 {
		dst = append(dst, '-')
		f = -f
	}
	var scratch [32]byte
	scientific := strconv.AppendFloat(scratch[:0], f, 'e', -1, 64)
	mark := bytes.IndexByte(scientific, 'e')
	exponent, _ := strconv.Atoi(string(scientific[mark+1:]))
	var digitBuf [24]byte
	digits := append(digitBuf[:0], scientific[0])
	if mark > 2 {
		digits = append(digits, scientific[2:mark]...)
	}
	point := exponent + 1
	switch {
	case point > maxPositionalExponent || point <= minPositionalExponent:
		dst = append(dst, digits[0])
		if len(digits) > 1 {
			dst = append(dst, '.')
			dst = append(dst, digits[1:]...)
		}
		dst = append(dst, 'e')
		return strconv.AppendInt(dst, int64(exponent), 10)
	case point <= 0:
		dst = append(dst, '0', '.')
		for range -point {
			dst = append(dst, '0')
		}
		return append(dst, digits...)
	case point >= len(digits):
		dst = append(dst, digits...)
		for range point - len(digits) {
			dst = append(dst, '0')
		}
		return dst
	default:
		dst = append(dst, digits[:point]...)
		dst = append(dst, '.')
		return append(dst, digits[point:]...)
	}
}

// isValidJSONText reports whether ClickHouse's isValidJSON accepts s. The stored column cannot tell a string that
// holds an object or array from an object or array stored as text, so the builder asks isValidJSON and this mode must
// give the same answer. It is stricter than the cleaner's own parser: the text must be UTF-8, a surrogate escape
// needs its pair, a number with a fraction or an exponent must fit a Float64, and nesting stops at maxValidJSONDepth.
func isValidJSONText(s string) bool {
	if !utf8.ValidString(s) {
		return false
	}
	v := jsonValidator{data: s}
	v.skipWS()
	if !v.value(1) {
		return false
	}
	v.skipWS()
	return v.pos == len(v.data)
}

type jsonValidator struct {
	data string
	pos  int
}

func (v *jsonValidator) skipWS() {
	for v.pos < len(v.data) {
		switch v.data[v.pos] {
		case ' ', '\n', '\r', '\t':
			v.pos++
		default:
			return
		}
	}
}

func (v *jsonValidator) consume(c byte) bool {
	if v.pos < len(v.data) && v.data[v.pos] == c {
		v.pos++
		return true
	}
	return false
}

func (v *jsonValidator) value(depth int) bool {
	if depth > maxValidJSONDepth || v.pos >= len(v.data) {
		return false
	}
	switch c := v.data[v.pos]; {
	case c == '{':
		return v.object(depth)
	case c == '[':
		return v.array(depth)
	case c == '"':
		return v.str()
	case c == '-' || isDigit(c):
		return v.number()
	}
	for _, literal := range [...]string{"true", "false", "null"} {
		if strings.HasPrefix(v.data[v.pos:], literal) {
			v.pos += len(literal)
			return true
		}
	}
	return false
}

func (v *jsonValidator) object(depth int) bool {
	v.pos++
	v.skipWS()
	if v.consume('}') {
		return true
	}
	for {
		v.skipWS()
		if v.pos >= len(v.data) || v.data[v.pos] != '"' || !v.str() {
			return false
		}
		v.skipWS()
		if !v.consume(':') {
			return false
		}
		v.skipWS()
		if !v.value(depth + 1) {
			return false
		}
		v.skipWS()
		if v.consume('}') {
			return true
		}
		if !v.consume(',') {
			return false
		}
	}
}

func (v *jsonValidator) array(depth int) bool {
	v.pos++
	v.skipWS()
	if v.consume(']') {
		return true
	}
	for {
		v.skipWS()
		if !v.value(depth + 1) {
			return false
		}
		v.skipWS()
		if v.consume(']') {
			return true
		}
		if !v.consume(',') {
			return false
		}
	}
}

func (v *jsonValidator) str() bool {
	v.pos++
	for v.pos < len(v.data) {
		c := v.data[v.pos]
		v.pos++
		switch {
		case c == '"':
			return true
		case c < 0x20:
			return false
		case c != '\\':
			continue
		}
		if v.pos >= len(v.data) {
			return false
		}
		escape := v.data[v.pos]
		v.pos++
		switch escape {
		case '"', '\\', '/', 'b', 'f', 'n', 'r', 't':
		case 'u':
			r, ok := v.hex4()
			if !ok {
				return false
			}
			if r >= 0xdc00 && r <= 0xdfff {
				return false
			}
			if r >= 0xd800 && r <= 0xdbff {
				if !v.consume('\\') || !v.consume('u') {
					return false
				}
				low, ok := v.hex4()
				if !ok || low < 0xdc00 || low > 0xdfff {
					return false
				}
			}
		default:
			return false
		}
	}
	return false
}

func (v *jsonValidator) hex4() (rune, bool) {
	if v.pos+4 > len(v.data) {
		return 0, false
	}
	r, ok := hexRune(borrowedBytes(v.data[v.pos : v.pos+4]))
	v.pos += 4
	return r, ok
}

func (v *jsonValidator) digits() bool {
	start := v.pos
	for v.pos < len(v.data) && isDigit(v.data[v.pos]) {
		v.pos++
	}
	return v.pos > start
}

func (v *jsonValidator) number() bool {
	start := v.pos
	v.consume('-')
	if !v.consume('0') && !v.digits() {
		return false
	}
	if v.consume('.') && !v.digits() {
		return false
	}
	if v.consume('e') || v.consume('E') {
		if !v.consume('+') {
			v.consume('-')
		}
		if !v.digits() {
			return false
		}
	}
	return !overflowsFloat64(v.data[start:v.pos])
}

func looksLikeContainer(s string) bool {
	return len(s) > 0 && (s[0] == '[' || s[0] == '{')
}

// A string that holds a valid JSON object or array goes into the document as that object or array, whether the
// cleaner stored it or the SDK sent that text. The stored column does not record which one it was.
func writeExportString(buf *bytes.Buffer, s string) {
	if looksLikeContainer(s) && isValidJSONText(s) {
		buf.WriteString(s)
		return
	}
	writeJSONString(buf, s)
}

// The cast into the JSON column fails when a number that ClickHouse parses is outside the Float64 range, and the
// events view then stores the whole document as unparseable. ClickHouse parses each top-level number and every number
// in the flags map, at any depth. A number inside any other object or array stays text, so it cannot fail the cast.
func castFails(document *value) bool {
	for _, member := range document.entries {
		if hasOverflowingNumber(member.value) {
			return true
		}
	}
	return false
}

func hasOverflowingNumber(v *value) bool {
	switch v.kind {
	case kindNumber:
		return overflowsFloat64(v.s)
	case kindObject:
		for _, member := range v.entries {
			if hasOverflowingNumber(member.value) {
				return true
			}
		}
	case kindArray:
		for _, child := range v.values {
			if hasOverflowingNumber(child) {
				return true
			}
		}
	}
	return false
}

// A Go map never shrinks, and clearing one costs time in proportion to its largest size, so one wide document must
// not leave its map behind for every later document to clear.
func (p *processor) releaseExportKeys() {
	if len(p.exportKeys) > maxRecycledValues {
		p.exportKeys = nil
		return
	}
	clear(p.exportKeys)
}

func (p *processor) writeExportMembers(buf *bytes.Buffer, document *value, isDeclaredString func(string) bool, hasMember bool) bool {
	decodeDots := false
	for _, member := range document.entries {
		if strings.Contains(member.key, escapedDot) {
			decodeDots = true
			break
		}
	}
	if decodeDots {
		if p.exportKeys == nil {
			p.exportKeys = make(map[string]struct{}, len(document.entries))
		}
		// The keys can borrow the input row, so the set must not outlive this document.
		defer p.releaseExportKeys()
	}
	for _, member := range document.entries {
		key := member.key
		if decodeDots {
			// Two keys can decode to one path. The JSON column keeps the first.
			key = strings.ReplaceAll(key, escapedDot, ".")
			if _, seen := p.exportKeys[key]; seen {
				continue
			}
			p.exportKeys[key] = struct{}{}
		}
		v := member.value
		declared := isDeclaredString != nil && isDeclaredString(key)
		if declared && v.kind == kindString && v.s == "" {
			// A declared path reads as '' on every row, so the builder treats '' under it as absent.
			continue
		}
		if v.kind == kindObject && len(v.entries) == 0 {
			// Every row has the flags map, so the builder leaves an empty one out.
			continue
		}
		if hasMember {
			buf.WriteByte(',')
		}
		hasMember = true
		writeJSONString(buf, key)
		buf.WriteByte(':')
		switch v.kind {
		case kindString:
			writeExportString(buf, v.s)
		case kindJSON:
			buf.WriteString(v.s)
		case kindNumber:
			if declared || readsBackAsString(v.s) {
				writeQuotedNumber(buf, v.s)
			} else {
				buf.WriteString(v.s)
			}
		case kindBool:
			writeExportBool(buf, v.b, declared)
		case kindObject:
			p.writeExportFlags(buf, v)
		default:
			p.writeValue(buf, v)
		}
	}
	return hasMember
}

// readsBackAsString reports whether the builder returns the number num as a string. ClickHouse prints a Float64 that
// has no fraction and is below 1e21 as bare digits. The builder then reads those digits as an integer, and it returns
// an integer outside the Int64 and UInt64 ranges as a string. Only a number with an exponent or 19 digits can be that
// large.
func readsBackAsString(num string) bool {
	if !isFloatToken(num) || len(num) < minStringifiedIntegerLength && !strings.ContainsAny(num, "eE") {
		return false
	}
	var scratch [64]byte
	return shouldStringifyNumber(borrowedString(appendClickHouseNumber(scratch[:0], num)))
}

func writeQuotedNumber(buf *bytes.Buffer, num string) {
	buf.WriteByte('"')
	buf.Write(appendClickHouseNumber(buf.AvailableBuffer(), num))
	buf.WriteByte('"')
}

func writeExportBool(buf *bytes.Buffer, b, asString bool) {
	text := "false"
	if b {
		text = "true"
	}
	if asString {
		buf.WriteByte('"')
		buf.WriteString(text)
		buf.WriteByte('"')
		return
	}
	buf.WriteString(text)
}

// The events table declares $feature_flags as a map of strings, so each flag value is written as the string the
// column stores: a boolean as its name, a number in ClickHouse's spelling, and an object or array as the JSON text
// ClickHouse prints after it parses that value.
func (p *processor) writeExportFlags(buf *bytes.Buffer, flags *value) {
	buf.WriteByte('{')
	for i, flag := range flags.entries {
		if i > 0 {
			buf.WriteByte(',')
		}
		writeJSONString(buf, flag.key)
		buf.WriteByte(':')
		switch v := flag.value; v.kind {
		case kindString:
			writeJSONString(buf, v.s)
		case kindNumber:
			writeQuotedNumber(buf, v.s)
		case kindBool:
			writeExportBool(buf, v.b, true)
		default:
			p.flagBuf.Reset()
			p.writeValueAt(&p.flagBuf, v, styleClickHouse)
			writeJSONString(buf, borrowedString(p.flagBuf.Bytes()))
		}
	}
	buf.WriteByte('}')
}

func writeExportUnparseable(buf *bytes.Buffer, raw []byte) {
	writeJSONString(buf, unparseablePropertiesKey)
	buf.WriteByte(':')
	writeExportString(buf, borrowedString(raw))
}

// The events table keeps the temporary members in a separate column, but a read of the event returns them in the
// properties, so the properties document holds them too.
func (p *processor) writeExportEventDocuments(properties, temporary *bytes.Buffer, cleaned, cleanedTemporary *value, raw []byte) {
	temporary.WriteByte('{')
	// The view stores no temporary properties at all when their cast fails.
	if cleanedTemporary != nil && !castFails(cleanedTemporary) {
		p.writeExportMembers(temporary, cleanedTemporary, nil, false)
	}
	temporary.WriteByte('}')

	properties.WriteByte('{')
	hasMember := false
	if castFails(cleaned) {
		writeExportUnparseable(properties, raw)
		hasMember = true
	} else {
		hasMember = p.writeExportMembers(properties, cleaned, isDeclaredEventStringPath, false)
	}
	if members := temporary.Bytes()[1 : temporary.Len()-1]; len(members) > 0 {
		if hasMember {
			properties.WriteByte(',')
		}
		properties.Write(members)
	}
	properties.WriteByte('}')
}

func (p *processor) writeExportPersonDocument(buf *bytes.Buffer, cleaned *value, raw []byte) {
	buf.WriteByte('{')
	if castFails(cleaned) {
		writeExportUnparseable(buf, raw)
	} else {
		p.writeExportMembers(buf, cleaned, isDeclaredPersonStringPath, false)
	}
	buf.WriteByte('}')
}
