package main

import (
	"bytes"
	"fmt"
	"strings"
	"testing"
)

func TestExportEnvelopeWritesWhatAReadOfTheEventsTableReturns(t *testing.T) {
	proc := newProcessor(eventExportEnvelope)
	tests := []struct {
		name, properties, person string
		want                     envelopeResult
	}{
		{
			"objects and arrays are JSON, and a top-level null is dropped and recorded",
			`{"plan": { "seats" : 5, "gone":null, "id":18446744073709551616, "cost": 2.0 },"path":["a\/b","\u0041","\u001f\u2028"],"n":1.0,"empty_object":{},"empty_array":[],"sent_null":null}`,
			`{"address":{"zip": "1", "city":null},"tags":[null, {"b": 1e3, "a": -0.0}],"gone":null}`,
			envelopeResult{
				Properties:               `{"plan":{"cost":2.0,"gone":null,"id":18446744073709551616,"seats":5},"path":["a/b","A","\u001F\u2028"],"n":1.0,"empty_object":{},"empty_array":[]}`,
				TemporaryProperties:      `{}`,
				PersonProperties:         `{"address":{"city":null,"zip":"1"},"tags":[null,{"a":-0.0,"b":1e3}]}`,
				PropertiesNullKeys:       []string{"sent_null"},
				PersonPropertiesNullKeys: []string{"gone"},
			},
		},
		{
			"a declared string path holds a string, and an empty one is absent",
			`{"$browser":"Chrome","$browser_version":120,"$lib_version":1.50,"$os":"","$pathname":1e3,"$device_type":true,"$host":{"x":1},"$session_id":-0.0,"$window_id":1e-7,"$current_url":"","other":""}`,
			`{"$browser":5,"$initial_os":"","$os_version":1E5,"name":""}`,
			envelopeResult{
				Properties:          `{"$browser":"Chrome","$browser_version":"120","$lib_version":"1.5","$pathname":"1000","$device_type":"true","$host":{"x":1},"$session_id":"-0","$window_id":"1e-7","other":""}`,
				TemporaryProperties: `{}`,
				PersonProperties:    `{"$browser":"5","$os_version":"100000","name":""}`,
			},
		},
		{
			"every flag value is a string, and person properties have no flags map",
			`{"$feature/demo":"control","$feature/on":true,"$feature/off":"false","$feature/num":1e3,"$feature/gone":null,"$feature_flags":{"old":"x","obj":{"z":1.0,"a":"b/c","n":null},"list":[1.50,null]},"$active_feature_flags":["demo"]}`,
			`{"$feature_flags":{"p":1}}`,
			envelopeResult{
				Properties:          `{"$feature_flags":{"demo":"control","list":"[1.5,null]","num":"1000","obj":"{\"z\":1,\"a\":\"b\\/c\"}","off":"$false","old":"x","on":"true"}}`,
				TemporaryProperties: `{}`,
				PersonProperties:    `{"$feature_flags":{"p":1}}`,
				PropertiesNullKeys:  []string{"$feature_flags.obj.n", "$feature_flags.gone"},
			},
		},
		{
			"an empty flags map is absent",
			`{"$feature_flags":{},"k":1}`,
			`{}`,
			envelopeResult{Properties: `{"k":1}`, TemporaryProperties: `{}`, PersonProperties: `{}`},
		},
		{
			"temporary properties are in both documents",
			`{"$set":{"email":"a@example.com"},"$set_once":{},"$unset":["a"],"$sdk_debug_probe":1,"$group_set":null,"custom":"kept"}`,
			`{}`,
			envelopeResult{
				Properties:                  `{"custom":"kept","$set":{"email":"a@example.com"},"$set_once":{},"$unset":["a"],"$sdk_debug_probe":1}`,
				TemporaryProperties:         `{"$set":{"email":"a@example.com"},"$set_once":{},"$unset":["a"],"$sdk_debug_probe":1}`,
				PersonProperties:            `{}`,
				TemporaryPropertiesNullKeys: []string{"$group_set"},
			},
		},
		{
			"a string is JSON only when ClickHouse accepts it as an object or array",
			`{"array":"[1,2]","object":"{\"a\":1}","spaced":"[1, 2 ]\n","cut":"[1,2","leading_space":" [1]","two_documents":"{}{}","empty":"{}","out_of_range":"[1e400]","lone_surrogate":"[\"\\ud800\"]","text":"plain"}`,
			`{"tags":"[\"a\"]"}`,
			envelopeResult{
				Properties:          `{"array":[1,2],"object":{"a":1},"spaced":[1, 2 ]` + "\n" + `,"cut":"[1,2","leading_space":" [1]","two_documents":"{}{}","empty":{},"out_of_range":"[1e400]","lone_surrogate":"[\"\\ud800\"]","text":"plain"}`,
				TemporaryProperties: `{}`,
				PersonProperties:    `{"tags":["a"]}`,
			},
		},
		{
			"an escaped dot in a key reads back as a dot, and the first key of a path wins",
			`{"a.b":1,"a%2Eb":2,"c%2Ed":3,"c.d":4,"lower%2e":5}`,
			`{"x%2Ey":"v"}`,
			envelopeResult{Properties: `{"a.b":1,"c.d":3,"lower%2e":5}`, TemporaryProperties: `{}`, PersonProperties: `{"x.y":"v"}`},
		},
		{
			"a float that prints as an integer outside the 64-bit ranges is a string",
			`{"fits":1e19,"too_big":2e19,"too_small":-1e19,"exponent_form":1e21,"fraction":1.5,"integer":18446744073709551615}`,
			`{"too_big":123456789012345678901.5}`,
			envelopeResult{
				Properties:          `{"fits":1e19,"too_big":"20000000000000000000","too_small":"-10000000000000000000","exponent_form":1e21,"fraction":1.5,"integer":18446744073709551615}`,
				TemporaryProperties: `{}`,
				PersonProperties:    `{"too_big":"123456789012345680000"}`,
			},
		},
		{
			"an out-of-range number makes its document unparseable, and temporary properties still follow",
			`{"k":1e400,"$set":{"a":1}}`,
			`{"n":-1e400,"m":1}`,
			envelopeResult{
				Properties:          `{"$unparseable_properties":"{\"k\":1e400,\"$set\":{\"a\":1}}","$set":{"a":1}}`,
				TemporaryProperties: `{"$set":{"a":1}}`,
				PersonProperties:    `{"$unparseable_properties":"{\"n\":-1e400,\"m\":1}"}`,
			},
		},
		{
			"an out-of-range temporary number drops every temporary property",
			`{"k":1,"$sdk_debug_probe":1e400,"$set":{"a":1}}`,
			`{}`,
			envelopeResult{Properties: `{"k":1}`, TemporaryProperties: `{}`, PersonProperties: `{}`},
		},
		{
			"an out-of-range number at any depth of the flags map makes the document unparseable",
			`{"$feature_flags":{"f":{"deep":[1e400]}},"k":1}`,
			`{}`,
			envelopeResult{
				Properties:          `{"$unparseable_properties":"{\"$feature_flags\":{\"f\":{\"deep\":[1e400]}},\"k\":1}"}`,
				TemporaryProperties: `{}`,
				PersonProperties:    `{}`,
			},
		},
		{
			"an object with an out-of-range number stays the string the events table stores",
			`{"o":{"n":1e400,"m":1}}`,
			`{}`,
			envelopeResult{Properties: `{"o":"{\"m\":1,\"n\":1e400}"}`, TemporaryProperties: `{}`, PersonProperties: `{}`},
		},
		{
			"quarantined input follows the string rule",
			`[1,2]`,
			`[1`,
			envelopeResult{
				Properties:          `{"$unparseable_properties":[1,2]}`,
				TemporaryProperties: `{}`,
				PersonProperties:    `{"$unparseable_properties":"[1"}`,
			},
		},
		{
			"a flags value that is not an object is kept as unparseable",
			`{"$feature_flags":"notobject","k":1}`,
			` `,
			envelopeResult{
				Properties:          `{"k":1,"$unparseable_properties":{"$feature_flags":"notobject"}}`,
				TemporaryProperties: `{}`,
				PersonProperties:    `{}`,
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := processEnvelope(t, &proc, tt.properties, tt.person)
			if fmt.Sprint(got) != fmt.Sprint(tt.want) {
				t.Fatalf("got  %+v\nwant %+v", got, tt.want)
			}
		})
	}
}

// The event mode stores an object as a string of this text, so a string of export mode must hold the same text.
func TestExportEnvelopeKeepsTheStoredTextOfAnObjectClickHouseRejects(t *testing.T) {
	properties := `{"o":{"z":"q\"\\\u0001\u2028/","n":1e400,"a":[1.50,null]}}`
	event := newProcessor(eventEnvelope)
	export := newProcessor(eventExportEnvelope)
	stored := processEnvelope(t, &event, properties, `{}`).Properties
	exported := processEnvelope(t, &export, properties, `{}`).Properties
	if stored != exported {
		t.Fatalf("export mode wrote %s, event mode stores %s", exported, stored)
	}
}

func TestRunChunkedExportEnvelope(t *testing.T) {
	input := "1\n" + `{"properties":"{\"keep\":{\"a\":1},\"$set\":{\"b\":2}}","person_properties":"{\"p\":null}"}` + "\n"
	var output bytes.Buffer
	if err := runChunked(strings.NewReader(input), &output, eventExportEnvelope); err != nil {
		t.Fatal(err)
	}
	want := `{"result":{"properties":"{\"keep\":{\"a\":1},\"$set\":{\"b\":2}}","temporary_properties":"{\"$set\":{\"b\":2}}","person_properties":"{}","properties_null_keys":[],"temporary_properties_null_keys":[],"person_properties_null_keys":["p"]}}` + "\n"
	if output.String() != want {
		t.Fatalf("runChunked() = %s, want %s", output.String(), want)
	}
}

// Each expectation is the answer of ClickHouse's isValidJSON for that text.
func TestIsValidJSONTextMatchesClickHouse(t *testing.T) {
	nested := func(open, inner, closing string, depth int) string {
		return strings.Repeat(open, depth) + inner + strings.Repeat(closing, depth)
	}
	tests := []struct {
		name, text string
		want       bool
	}{
		{"array", `[1,2]`, true},
		{"object", `{"a":{"b":[1,null,true,false]}}`, true},
		{"whitespace around values", "[\n1 ,\t2\r]\n", true},
		{"form feed is not whitespace", "[\f1]", false},
		{"no-break space is not whitespace", "[\u00a01]", false},
		{"trailing text", `[] x`, false},
		{"two documents", `{}{}`, false},
		{"trailing comma in an array", `[1,]`, false},
		{"trailing comma in an object", `{"a":1,}`, false},
		{"missing value", `{"a":}`, false},
		{"key that is not a string", `{1:1}`, false},
		{"single quotes", `{'a':1}`, false},
		{"duplicate keys", `{"a":1,"a":2}`, true},
		{"empty key", `{"":1}`, true},
		{"capitalized literal", `[True]`, false},
		{"nan", `[NaN]`, false},
		{"leading zero", `[01]`, false},
		{"negative leading zero", `[-01]`, false},
		{"lone minus", `[-]`, false},
		{"plus sign", `[+1]`, false},
		{"fraction without digits", `[1.]`, false},
		{"fraction without integer", `[.5]`, false},
		{"exponent without digits", `[1e+]`, false},
		{"hex number", `[0x10]`, false},
		{"negative zero", `[-0]`, true},
		{"zero with exponent", `[-0.0e-0]`, true},
		{"exponent with sign", `[1.5E+3]`, true},
		{"integer of any length", "[" + strings.Repeat("9", 400) + "]", true},
		{"largest Float64", `[1.7976931348623157e308]`, true},
		{"just above the largest Float64", `[1.7976931348623159e308]`, false},
		{"exponent above the Float64 range", `[-1e400]`, false},
		{"long number with a fraction above the Float64 range", "[" + strings.Repeat("9", 400) + ".0]", false},
		{"exponent below the Float64 range", `[1e-400]`, true},
		{"escapes", `["\b\f\n\r\t\"\\\/"]`, true},
		{"escaped NUL", `["\u0000"]`, true},
		{"unknown escape", `["\x"]`, false},
		{"short unicode escape", `["\u12"]`, false},
		{"unicode escape with a letter outside hex", `["\u00zz"]`, false},
		{"raw control character", "[\"\t\"]", false},
		{"raw DEL", "[\"\x7f\"]", true},
		{"unterminated string", `["abc]`, false},
		{"surrogate pair", `["\ud83d\ude00"]`, true},
		{"lone high surrogate", `["\ud800"]`, false},
		{"lone low surrogate", `["\udc00"]`, false},
		{"high surrogate before text", `["\ud800a"]`, false},
		{"high surrogate before a non-surrogate escape", `["\ud800\u0041"]`, false},
		{"four-byte UTF-8", "[\"\xf0\x9f\x98\x80\"]", true},
		{"invalid UTF-8 byte", "[\"\xff\"]", false},
		{"truncated UTF-8", "[\"\xc3\"]", false},
		{"overlong UTF-8", "[\"\xc0\xaf\"]", false},
		{"UTF-8 encoded surrogate", "[\"\xed\xa0\x80\"]", false},
		{"empty arrays at the depth limit", nested("[", "", "]", 1024), true},
		{"empty arrays over the depth limit", nested("[", "", "]", 1025), false},
		{"scalar at the depth limit", nested("[", "1", "]", 1023), true},
		{"scalar over the depth limit", nested("[", "1", "]", 1024), false},
		{"objects at the depth limit", nested(`{"a":`, "{}", "}", 1023), true},
		{"objects over the depth limit", nested(`{"a":`, "{}", "}", 1024), false},
		{"empty text", ``, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := isValidJSONText(tt.text); got != tt.want {
				t.Fatalf("isValidJSONText() = %v, want %v", got, tt.want)
			}
		})
	}
}

// Each expectation is the text ClickHouse stores when it reads that JSON number into a String path.
func TestAppendClickHouseNumberMatchesClickHouse(t *testing.T) {
	tests := []struct{ num, want string }{
		{"120", "120"},
		{"-0", "0"},
		{"18446744073709551615", "18446744073709551615"},
		{"9007199254740993", "9007199254740993"},
		{"0.0", "0"},
		{"-0.0", "-0"},
		{"0e0", "0"},
		{"1.50", "1.5"},
		{"-123.0", "-123"},
		{"0.1e1", "1"},
		{"100e-2", "1"},
		{"1E+2", "100"},
		{"123456.789e3", "123456789"},
		{"123456789.123456789", "123456789.12345679"},
		{"0.30000000000000004441", "0.30000000000000004"},
		{"9007199254740993.0", "9007199254740992"},
		{"0.00001234", "0.00001234"},
		{"1e-6", "0.000001"},
		{"1.5e-6", "0.0000015"},
		{"9.9e-7", "9.9e-7"},
		{"1e-7", "1e-7"},
		{"-1.5e-10", "-1.5e-10"},
		{"1e-999", "0"},
		{"4.9e-324", "5e-324"},
		{"1e15", "1000000000000000"},
		{"12345678901234567890.0", "12345678901234567000"},
		{"1e20", "100000000000000000000"},
		{"9.999999999999999e20", "999999999999999900000"},
		{"1.0e21", "1e21"},
		{"-1e21", "-1e21"},
		{"1234567890123456789012.0", "1.2345678901234568e21"},
		{"1.7976931348623157e308", "1.7976931348623157e308"},
	}
	for _, tt := range tests {
		t.Run(tt.num, func(t *testing.T) {
			if got := string(appendClickHouseNumber(nil, tt.num)); got != tt.want {
				t.Fatalf("appendClickHouseNumber() = %s, want %s", got, tt.want)
			}
		})
	}
}

func BenchmarkProcessEnvelope(b *testing.B) {
	row := []byte(`{"properties":"{\"$browser\":\"Chrome\",\"$browser_version\":120,\"$current_url\":\"https://example.com/docs/getting-started?ref=nav\",\"$device_type\":\"Desktop\",\"$geoip_city_name\":\"Springfield\",\"$geoip_country_code\":\"US\",\"$host\":\"example.com\",\"$lib\":\"web\",\"$lib_version\":\"1.200.0\",\"$os\":\"Mac OS X\",\"$pathname\":\"/docs/getting-started\",\"$session_id\":\"0190a000-0000-7000-8000-000000000001\",\"$window_id\":\"0190a000-0000-7000-8000-000000000002\",\"$viewport_height\":900,\"$viewport_width\":1440,\"$feature/new-nav\":true,\"$feature/pricing-test\":\"variant-b\",\"$active_feature_flags\":[\"new-nav\",\"pricing-test\"],\"$set\":{\"plan\":\"scale\",\"seats\":25,\"tags\":[\"docs\",\"trial\"]},\"$set_once\":{\"first_seen_path\":\"/\"},\"$sdk_debug_retry_queue_size\":0,\"title\":\"Getting started\",\"cart\":{\"items\":[{\"sku\":\"a-1\",\"price\":19.99,\"qty\":2},{\"sku\":\"b-2\",\"price\":5,\"qty\":1}],\"currency\":\"USD\"},\"referrer\":null,\"scroll_depth\":0.42}","person_properties":"{\"$browser\":\"Chrome\",\"$initial_browser\":\"Safari\",\"$os\":\"Mac OS X\",\"email\":\"user@example.com\",\"plan\":\"scale\",\"seats\":25,\"tags\":[\"docs\",\"trial\"],\"company\":{\"name\":\"Example\",\"size\":120}}"}`)
	for _, mode := range []struct {
		name string
		kind propertiesKind
	}{{"event", eventEnvelope}, {"export", eventExportEnvelope}} {
		b.Run(mode.name, func(b *testing.B) {
			proc := newProcessor(mode.kind)
			var buf bytes.Buffer
			b.ReportAllocs()
			b.SetBytes(int64(len(row)))
			for i := 0; i < b.N; i++ {
				if err := proc.processLine(row, &buf); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}
