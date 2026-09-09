package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"weak"
)

func TestProcessLineCleansEventProperties(t *testing.T) {
	input := []byte(`{"$active_feature_flags":"undefined","$active_feature_flags":["beta",42,null,{"a.b":1}],"Account.client_id":"abc","Account":{"client_id":null},"huge":18446744073709551616,"max_uint":18446744073709551615,"too_negative":-9223372036854775809,"min_int":-9223372036854775808,"null_field":null,"dupe":"","dupe":"kept","emptydupe":"","emptydupe":null}`)
	want := `{"Account":{"client_id":"abc"},"huge":"18446744073709551616","max_uint":18446744073709551615,"too_negative":"-9223372036854775809","min_int":-9223372036854775808,"dupe":"kept","emptydupe":""}`

	for _, width := range []int{0, 16, 256} {
		var prefix strings.Builder
		prefix.WriteByte('{')
		for i := range width {
			fmt.Fprintf(&prefix, `"key%d":%d,`, i, i)
		}
		var got bytes.Buffer
		if err := processLine([]byte(prefix.String()+string(input[1:])), &got); err != nil {
			t.Fatal(err)
		}
		if expected := prefix.String() + want[1:]; got.String() != expected {
			t.Fatalf("processLine() = %s, want %s", got.String(), expected)
		}
	}
}

func TestProcessLineDropsHighVolumeEventProperties(t *testing.T) {
	input := []byte(`{"$ai_input":"input","$ai_output":"output","$ai_output_choices":["choice"],"$ai_input_state":{"state":1},"$ai_output_state":{"state":2},"$ai_tools":["tool"],"ph_product_tours":true,"$session_recording_remote_config":{"enabled":true},"$product_tours_activated":true,"$product_tours_enabled_server_side":true,"$surveys_activated":true,"$active_feature_flags":["flag"],"$feature_flag_payload":"payload","$feature_flag_bootstrapped_payload":true,"$feature_flag_original_payload":{"key":"value"},"$feature_flag_payloads":{"flag":"payload"},"$set":{"name":"value"},"$set_once":{"initial":"value"},"$unset":["old_property"],"$transformations_succeeded":["one"],"$transformations_skipped":["two"],"kept":"value"}`)
	want := `{"kept":"value"}`

	var got bytes.Buffer
	if err := processLine(input, &got); err != nil {
		t.Fatal(err)
	}
	if got.String() != want {
		t.Fatalf("processLine() = %s, want %s", got.String(), want)
	}
}

func TestProcessLinePreservesPersonProperties(t *testing.T) {
	input := []byte(`{"$active_feature_flags":["flag"],"$feature/test":true,"$set":{"name":"value"},"nested.key":"value","drop":null}`)
	want := `{"$active_feature_flags":["flag"],"$feature/test":true,"$set":{"name":"value"},"nested":{"key":"value"}}`

	var got bytes.Buffer
	proc := processor{kind: personProperties}
	if err := proc.processLine(input, &got); err != nil {
		t.Fatal(err)
	}
	if got.String() != want {
		t.Fatalf("processLine() = %s, want %s", got.String(), want)
	}
}

func TestProcessLineGroupsFeaturePropertiesAndPreservesExistingFlagValues(t *testing.T) {
	tests := map[string]string{
		`{"$feature_flags.z":true,"$feature_flags.a":false,"other":1}`: `{"$feature_flags":{"a":false,"z":true},"other":1}`,
		`{"$feature/first-flag":"fresh","$feature/number":42,"$feature/enabled":true,"$feature/config":{"nested.value":"dropped"},"$feature_flags":"invalid","$feature_flags":{"existing":"kept","first-flag":"existing"},"$feature_flag_payloads":{"flag":"dropped"},"other":"value"}`: `{"$feature_flags":{"config":{"nested":{"value":"dropped"}},"enabled":true,"existing":"kept","first-flag":"existing","number":42},"other":"value"}`,
		`{"$feature/zebra":false,"$feature/alpha":"control","other":1}`: `{"other":1,"$feature_flags":{"alpha":"control","zebra":false}}`,
		`{"$feature_flags":{"zebra":false,"alpha":"control"}}`:          `{"$feature_flags":{"alpha":"control","zebra":false}}`,
		`{"$feature/a.b":1,"$feature/a":{"b":2},"$feature/Z":true}`:     `{"$feature_flags":{"Z":true,"a":{"b":1}}}`,
	}

	for input, want := range tests {
		var got bytes.Buffer
		if err := processLine([]byte(input), &got); err != nil {
			t.Fatalf("processLine(%s) returned error: %v", input, err)
		}
		if got.String() != want {
			t.Fatalf("processLine(%s) = %s, want %s", input, got.String(), want)
		}
	}
}

func TestEventPropertyRulesCoverComplexSchemaPaths(t *testing.T) {
	tests := map[normalizationKind][]string{
		normalizationStringArray: {
			"$exception_functions",
			"$exception_sources",
			"$exception_types",
			"$exception_values",
			"$mcp_listed_tool_names",
		},
		normalizationObjectArray: {
			"$exception_list",
		},
	}

	for want, paths := range tests {
		for _, path := range paths {
			rule := eventPropertyRules.children[path]
			if rule == nil {
				t.Errorf("missing normalization rule for %s", path)
				continue
			}
			if rule.normalization != want {
				t.Errorf("normalization rule for %s = %v, want %v", path, rule.normalization, want)
			}
		}
	}
}

func TestProcessLinePreservesScalarPropertiesAndNormalizesComplexProperties(t *testing.T) {
	input := []byte(`{"$agent_turn":"42.0","$ai_total_cost_usd":{"currency":"USD"},"$is_identified":"yes","created_by_system":"scheduler","$mcp_listed_tool_names":"search","$exception_list":"{\"type\":\"TypeError\",\"value\":null}"}`)
	want := `{"$agent_turn":"42.0","$ai_total_cost_usd":{"currency":"USD"},"$is_identified":"yes","created_by_system":"scheduler","$mcp_listed_tool_names":["search"],"$exception_list":[{"type":"TypeError"}]}`

	var got bytes.Buffer
	if err := processLine(input, &got); err != nil {
		t.Fatal(err)
	}
	if got.String() != want {
		t.Fatalf("processLine() = %s, want %s", got.String(), want)
	}
}

func TestProcessLineQuarantinesInvalidExceptionList(t *testing.T) {
	tests := map[string]string{
		`{"$unparseable_properties":"spoofed","$exception_list":"[redacted]","kept":"value"}`: `{"$exception_list":[],"kept":"value","$unparseable_properties":"{\"$exception_list\":\"[redacted]\"}"}`,
		`{"$exception_list":[1]}`:  `{"$exception_list":[],"$unparseable_properties":"{\"$exception_list\":[1]}"}`,
		`{"$exception_list":true}`: `{"$exception_list":[],"$unparseable_properties":"{\"$exception_list\":true}"}`,
	}

	for input, want := range tests {
		var got bytes.Buffer
		if err := processLine([]byte(input), &got); err != nil {
			t.Fatalf("processLine(%s) returned error: %v", input, err)
		}
		if got.String() != want {
			t.Fatalf("processLine(%s) = %s, want %s", input, got.String(), want)
		}
	}
}

func TestProcessLineQuarantinesExcessiveDepth(t *testing.T) {
	tests := map[string]string{
		"nested JSON":            strings.Repeat(`{"x":`, maxJSONDepth) + `1` + strings.Repeat(`}`, maxJSONDepth),
		"dotted key":             `{"` + strings.Repeat("x.", maxJSONDepth) + `x":1}`,
		"nested arrays":          `{"x":` + strings.Repeat(`[`, 9) + `1` + strings.Repeat(`]`, 9) + `}`,
		"arrays through objects": `{"x":` + strings.Repeat(`[{"x":`, 9) + `1` + strings.Repeat(`}]`, 9) + `}`,
		"temporary property":     `{"$set":` + strings.Repeat(`[`, 9) + `1` + strings.Repeat(`]`, 9) + `}`,
		"arrays with nulls":      `{"x":` + strings.Repeat(`[`, 24) + `[0]` + strings.Repeat(`,null]`, 24) + `}`,
	}
	for name, input := range tests {
		for _, kind := range []propertiesKind{eventProperties, personProperties, temporaryProperties} {
			t.Run(fmt.Sprintf("%s/%d", name, kind), func(t *testing.T) {
				var got bytes.Buffer
				proc := processor{kind: kind}
				if err := proc.processLine([]byte(input), &got); err != nil {
					t.Fatal(err)
				}
				want := fmt.Sprintf(`{"$unparseable_properties":%q}`, input)
				if kind == temporaryProperties {
					want = `{}`
				}
				if got.String() != want {
					t.Fatalf("processLine() = %s, want %s", got.String(), want)
				}
			})
		}
	}
}

func TestProcessLineArrayDepthBoundary(t *testing.T) {
	for _, depth := range []int{7, 8} {
		arrays := strings.Repeat(`[`, depth) + `1` + strings.Repeat(`]`, depth)
		input := `{"x":` + arrays + `,"$set":` + arrays + `}`
		for _, kind := range []propertiesKind{eventProperties, personProperties, temporaryProperties} {
			t.Run(fmt.Sprintf("%d/%d", depth, kind), func(t *testing.T) {
				var got bytes.Buffer
				proc := processor{kind: kind}
				if err := proc.processLine([]byte(input), &got); err != nil {
					t.Fatal(err)
				}
				want := input
				if kind == eventProperties {
					want = `{"x":` + arrays + `}`
				} else if kind == temporaryProperties {
					want = `{"$set":` + arrays + `}`
				}
				if got.String() != want {
					t.Fatalf("processLine() = %s, want %s", got.String(), want)
				}
			})
		}
	}
}

func TestProcessLineDottedDepthBoundary(t *testing.T) {
	for _, depth := range []int{maxJSONDepth - 1, maxJSONDepth} {
		for _, leaf := range []string{`1`, `{}`, `{"y":1}`, `[1]`} {
			input := `{"` + strings.Repeat("x.", depth-2) + `x":` + leaf + `}`
			want := strings.Repeat(`{"x":`, depth-1) + leaf + strings.Repeat(`}`, depth-1)
			if depth == maxJSONDepth && (leaf == `{"y":1}` || leaf == `[1]`) {
				want = fmt.Sprintf(`{"$unparseable_properties":%q}`, input)
			}
			var output bytes.Buffer
			if err := processLine([]byte(input), &output); err != nil {
				t.Fatal(err)
			}
			if output.String() != want {
				t.Fatalf("depth=%d leaf=%s: got %s, want %s", depth, leaf, output.String(), want)
			}
		}
	}
}

func TestProcessLineChecksArrayDepthAfterNormalization(t *testing.T) {
	for _, depth := range []int{7, 8} {
		object := `{"x":` + strings.Repeat(`[`, depth) + `1` + strings.Repeat(`]`, depth) + `}`
		input := fmt.Sprintf(`{"$exception_list":%q}`, object)
		var got bytes.Buffer
		if err := processLine([]byte(input), &got); err != nil {
			t.Fatal(err)
		}
		want := `{"$exception_list":[` + object + `]}`
		if depth == 8 {
			want = fmt.Sprintf(`{"$unparseable_properties":%q}`, input)
		}
		if got.String() != want {
			t.Fatalf("processLine() = %s, want %s", got.String(), want)
		}
	}
}

func TestTemporaryPropertiesDoNotDuplicateQuarantinedDocuments(t *testing.T) {
	for _, input := range []string{
		`{"$set":` + strings.Repeat(`{"x":`, maxJSONDepth) + `1` + strings.Repeat(`}`, maxJSONDepth) + `}`,
		`{"$set.` + strings.Repeat("x.", maxJSONDepth) + `x":1}`,
	} {
		proc := processor{kind: temporaryProperties}
		var got bytes.Buffer
		if err := proc.processLine([]byte(input), &got); err != nil {
			t.Fatal(err)
		}
		if got.String() != "{}" {
			t.Fatalf("temporary output must not retain raw quarantine: %s", got.String())
		}
	}
}

func TestProcessLineParsesStringifiedArrayPath(t *testing.T) {
	input := []byte(`{"$exception_types":"[\"TypeError\",7,null,{\"x.y\":\"z\"}]"}`)
	want := `{"$exception_types":["TypeError","7","","{\"x\":{\"y\":\"z\"}}"]}`

	var got bytes.Buffer
	if err := processLine(input, &got); err != nil {
		t.Fatal(err)
	}
	if got.String() != want {
		t.Fatalf("processLine() = %s, want %s", got.String(), want)
	}
}

func TestProcessLineCoercesArrayPathScalars(t *testing.T) {
	tests := map[string]string{
		`{"$exception_sources":"undefined"}`:         `{"$exception_sources":[]}`,
		`{"$exception_sources":"worker"}`:            `{"$exception_sources":["worker"]}`,
		`{"$exception_sources":false}`:               `{"$exception_sources":["false"]}`,
		`{"$exception_sources":{}}`:                  `{"$exception_sources":[]}`,
		`{"$exception_sources":{"worker.id":3}}`:     `{"$exception_sources":["{\"worker\":{\"id\":3}}"]}`,
		`{"nested":{"$exception_sources":"worker"}}`: `{"nested":{"$exception_sources":"worker"}}`,
	}

	for input, want := range tests {
		var got bytes.Buffer
		if err := processLine([]byte(input), &got); err != nil {
			t.Fatalf("processLine(%s) returned error: %v", input, err)
		}
		if got.String() != want {
			t.Fatalf("processLine(%s) = %s, want %s", input, got.String(), want)
		}
	}
}

func TestCleanNodeMatchesNestedArrayStringPath(t *testing.T) {
	input := []byte(`{"outer":[{"$exception_sources":"undefined"},{"$exception_sources":"worker"}],"nested":{"$exception_sources":"worker"}}`)
	want := `{"outer":[{"$exception_sources":[]},{"$exception_sources":["worker"]}],"nested":{"$exception_sources":"worker"}}`

	var proc processor
	proc.data = input
	parsed, err := proc.parseValue(1, 0)
	if err != nil {
		t.Fatal(err)
	}
	cleaned, err := proc.cleanNode(makePathRules("outer.$exception_sources"), parsed, 1)
	if err != nil {
		t.Fatal(err)
	}
	defer proc.recycle(cleaned)

	var got bytes.Buffer
	proc.writeValue(&got, cleaned)
	if got.String() != want {
		t.Fatalf("cleanNode() = %s, want %s", got.String(), want)
	}
}

func TestProcessLineHandlesEscapedDottedKeysAndStrings(t *testing.T) {
	input := []byte("{\"a\\u002eb\":\"line\\nquote\\\"\",\"emoji\":\"\\ud83d\\ude00\"}")
	want := "{\"a\":{\"b\":\"line\\nquote\\\"\"},\"emoji\":\"\U0001F600\"}"

	var got bytes.Buffer
	if err := processLine(input, &got); err != nil {
		t.Fatal(err)
	}
	if got.String() != want {
		t.Fatalf("processLine() = %s, want %s", got.String(), want)
	}
}

func TestProcessLineErrorsOnMalformedJSON(t *testing.T) {
	for _, invalid := range []string{
		`{"broken"`, `{"x":1,}`, `[1,]`, `01`, `1e`, `true false`,
		`"unterminated`, `"bad\q"`, `"bad\uXYZW"`, `"\ud800"`, `"\ud800\u0041"`,
		"\"control\x01\"", strings.Repeat(`[`, 9) + `1,]` + strings.Repeat(`]`, 8),
	} {
		for _, key := range []string{"keep", "$ai_input", "$set"} {
			for _, kind := range []propertiesKind{eventProperties, personProperties, temporaryProperties} {
				var got bytes.Buffer
				proc := processor{kind: kind}
				input := fmt.Sprintf(`{%q:%s}`, key, invalid)
				if err := proc.processLine([]byte(input), &got); err == nil {
					t.Fatalf("expected error for malformed JSON (%d): %s", kind, input)
				}
				if err := proc.processLine([]byte(`{"$set":1,"keep":2}`), &got); err != nil {
					t.Fatal(err)
				}
				want := `{"keep":2}`
				if kind == personProperties {
					want = `{"$set":1,"keep":2}`
				} else if kind == temporaryProperties {
					want = `{"$set":1}`
				}
				if got.String() != want {
					t.Fatalf("row after parse error = %s, want %s", got.String(), want)
				}
			}
		}
	}
}

func TestRunReusesInputBuffer(t *testing.T) {
	for _, size := range []int{31, 4*1024*1024 + 17} {
		text := strings.Repeat("x", size) + "\n\t\"\\😀"
		encoded, err := json.Marshal(text)
		if err != nil {
			t.Fatal(err)
		}
		row := `{"keep":` + string(encoded) + `,"$ai_input":` + string(encoded) + `}`
		cleaned := `{"keep":` + string(encoded) + `}`
		for _, newline := range []string{"\n", "\r\n"} {
			for _, chunked := range []bool{false, true} {
				input := row + newline + `{"keep":1}` + newline
				runner := run
				if chunked {
					input = "1\n" + row + newline + "1\n" + `{"keep":1}` + newline
					runner = runChunked
				}
				var got bytes.Buffer
				if err := runner(strings.NewReader(input), &got, eventProperties); err != nil {
					t.Fatal(err)
				}
				if got.String() != cleaned+"\n"+`{"keep":1}`+"\n" {
					t.Fatalf("incorrect output (size=%d, chunked=%t)", size, chunked)
				}
			}
		}
		var got bytes.Buffer
		if err := run(strings.NewReader(row), &got, eventProperties); err != nil || got.String() != cleaned {
			t.Fatalf("final row without newline: %v", err)
		}
		if err := runChunked(strings.NewReader("1\n"+row), io.Discard, eventProperties); err == nil {
			t.Fatal("expected truncated chunk to fail")
		}
	}
}

func TestProcessLineStringBytes(t *testing.T) {
	for _, offset := range []int{0, 7, 8, 15, 16, 31, 32} {
		for c := range 256 {
			input := []byte(`{"keep":"` + strings.Repeat("a", offset) + string([]byte{byte(c)}) + `x"}`)
			valid := c >= 0x20 && c != '"' && c != '\\'
			for _, kind := range []propertiesKind{eventProperties, personProperties, temporaryProperties} {
				var output bytes.Buffer
				proc := processor{kind: kind}
				err := proc.processLine(input, &output)
				if (err == nil) != valid {
					t.Fatalf("offset=%d byte=%d kind=%d: error=%v, valid=%t", offset, c, kind, err, valid)
				}
				if valid {
					want := input
					if kind == temporaryProperties {
						want = []byte(`{}`)
					}
					if !bytes.Equal(output.Bytes(), want) {
						t.Fatalf("offset=%d byte=%d kind=%d: got %q, want %q", offset, c, kind, output.Bytes(), want)
					}
				}
			}
		}
	}
}

func TestRunChunked(t *testing.T) {
	input := "2\n{\"drop\":null,\"keep\":1}\n{\"$feature/enabled\":true}\n1\n{\"drop\":null}\n"
	want := "{\"keep\":1}\n{\"$feature_flags\":{\"enabled\":true}}\n{}\n"
	var output bytes.Buffer

	if err := runChunked(strings.NewReader(input), &output, eventProperties); err != nil {
		t.Fatal(err)
	}
	if output.String() != want {
		t.Fatalf("runChunked() = %q, want %q", output.String(), want)
	}
}

func TestRunChunkedAfterArrayQuarantine(t *testing.T) {
	poison := `{"$set":` + strings.Repeat(`[`, 9) + `1` + strings.Repeat(`]`, 9) + `}`
	good := `{"keep":1,"$set":2}`
	input := "2\n" + poison + "\n" + good + "\n1\n" + good + "\n"
	for _, kind := range []propertiesKind{eventProperties, personProperties, temporaryProperties} {
		t.Run(fmt.Sprint(kind), func(t *testing.T) {
			quarantine := fmt.Sprintf(`{"$unparseable_properties":%q}`, poison)
			cleaned := good
			if kind == eventProperties {
				cleaned = `{"keep":1}`
			} else if kind == temporaryProperties {
				quarantine = `{}`
				cleaned = `{"$set":2}`
			}
			var output bytes.Buffer
			if err := runChunked(strings.NewReader(input), &output, kind); err != nil {
				t.Fatal(err)
			}
			want := quarantine + "\n" + cleaned + "\n" + cleaned + "\n"
			if output.String() != want {
				t.Fatalf("runChunked() = %q, want %q", output.String(), want)
			}
		})
	}
}

func TestProcessLineReleasesPreviousInput(t *testing.T) {
	for _, kind := range []propertiesKind{eventProperties, personProperties, temporaryProperties} {
		t.Run(fmt.Sprint(kind), func(t *testing.T) {
			proc := processor{kind: kind}
			var output bytes.Buffer
			input := []byte(`{"$set":1,"discard":null,"nested.path":2,"$sdk_debug_probe.path":3,"escaped\u002ekey":"line\n"}`)
			previousInput := weak.Make(&input[0])
			if err := proc.processLine(input, &output); err != nil {
				t.Fatal(err)
			}
			input = nil
			if err := proc.processLine([]byte(`{"$set":2}`), &output); err != nil {
				t.Fatal(err)
			}
			runtime.GC()
			if previousInput.Value() != nil {
				t.Error("processor retains a previous input after garbage collection")
			}
			runtime.KeepAlive(&proc)
		})
	}
}

func TestProcessLineReleasesOversizedContainers(t *testing.T) {
	var object strings.Builder
	object.WriteByte('{')
	for i := range 64 {
		if i > 0 {
			object.WriteByte(',')
		}
		fmt.Fprintf(&object, `"key%d":1`, i)
	}
	object.WriteByte('}')
	for name, input := range map[string]string{
		"object": object.String(),
		"array":  "[" + strings.Repeat("1,", 63) + "1]",
	} {
		t.Run(name, func(t *testing.T) {
			var proc processor
			var output bytes.Buffer
			if err := proc.processLine([]byte(input), &output); err != nil {
				t.Fatal(err)
			}
			var entries weak.Pointer[entry]
			var values weak.Pointer[*value]
			for _, v := range proc.free {
				if cap(v.entries) >= 64 {
					entries = weak.Make(&v.entries[:cap(v.entries)][0])
				}
				if cap(v.values) >= 64 {
					values = weak.Make(&v.values[:cap(v.values)][0])
				}
			}
			if entries.Value() == nil && values.Value() == nil {
				t.Fatal("wide row did not retain a reusable container")
			}
			if err := proc.processLine([]byte(`{}`), &output); err != nil {
				t.Fatal(err)
			}
			if output.String() != "{}" {
				t.Fatalf("unexpected output: %s", output.String())
			}
			runtime.GC()
			if entries.Value() != nil || values.Value() != nil {
				t.Error("small row retains an oversized container after garbage collection")
			}
			runtime.KeepAlive(&proc)
		})
	}
}

func TestProcessLineBoundsRetainedMemory(t *testing.T) {
	input := []byte(`{"keep":[` + strings.Repeat(`{"x":1},`, 8192) + `{}]}`)
	var proc processor
	var output bytes.Buffer
	if err := proc.processLine(input, &output); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(output.Bytes(), input) {
		t.Fatal("large retained property changed")
	}
	if len(proc.free) > maxRecycledValues {
		t.Fatalf("retained %d parser nodes after a large row", len(proc.free))
	}
	if err := proc.processLine([]byte(`{}`), &output); err != nil {
		t.Fatal(err)
	}
	if output.String() != "{}" || output.Cap() > 64*1024 {
		t.Fatalf("small row output length=%d capacity=%d", output.Len(), output.Cap())
	}
}

func TestProcessLineReusesDottedBuffers(t *testing.T) {
	var proc processor
	var output bytes.Buffer
	for _, width := range []int{32, 256, 4096, 17, 512, 32, 256, 1} {
		var input, expected strings.Builder
		input.WriteByte('{')
		expected.WriteString(`{"group":{`)
		for i := range width {
			if i > 0 {
				input.WriteByte(',')
				expected.WriteByte(',')
			}
			fmt.Fprintf(&input, `"group.key%d":%d`, i, i)
			fmt.Fprintf(&expected, `"key%d":%d`, i, i)
		}
		input.WriteByte('}')
		expected.WriteString("}}")
		if err := proc.processLine([]byte(input.String()), &output); err != nil {
			t.Fatal(err)
		}
		if output.String() != expected.String() {
			t.Fatalf("dotted expansion changed after buffer reuse at width %d", width)
		}
		retained := 0
		for _, entries := range proc.entryBuffers {
			retained += cap(entries)
			for _, entry := range entries[:cap(entries)] {
				if entry.key != "" || entry.value != nil {
					t.Fatal("cached entry retains input or a recycled value")
				}
			}
		}
		if retained >= 8192 {
			t.Fatalf("cached %d entries", retained)
		}
	}
	if err := proc.processLine([]byte(`{}`), &output); err != nil {
		t.Fatal(err)
	}
	if proc.entryBufferMask != 0 {
		t.Fatal("small row retains oversized cached buffers")
	}
}

func TestShouldStringifyNumber(t *testing.T) {
	tests := map[string]bool{
		"18446744073709551615":  false,
		"18446744073709551616":  true,
		"9223372036854775808":   false,
		"-9223372036854775808":  false,
		"-9223372036854775809":  true,
		"1.8446744073709552e19": false,
		"42":                    false,
	}

	for input, want := range tests {
		if got := shouldStringifyNumber(input); got != want {
			t.Fatalf("shouldStringifyNumber(%q) = %v, want %v", input, got, want)
		}
	}
}

func BenchmarkProcessLine(b *testing.B) {
	input := []byte(`{"$active_feature_flags":"[\"beta\", \"new-ui\"]","$exception_types":"undefined","Account.client_id":"client_123","huge":18446744073709551616,"small":123,"dotted.key":"value","duplicate":"","duplicate":"kept","null_field":null,"nested":{"a.b":{"c":1}}}`)
	var buf bytes.Buffer
	proc := processor{}

	b.ReportAllocs()
	b.SetBytes(int64(len(input)))

	for i := 0; i < b.N; i++ {
		if err := proc.processLine(input, &buf); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkProcessFixture(b *testing.B) {
	lines, totalBytes := loadBenchmarkLines(b)
	var buf bytes.Buffer
	proc := processor{}

	b.ReportAllocs()
	b.SetBytes(int64(totalBytes))
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		for _, line := range lines {
			if err := proc.processLine(line, &buf); err != nil {
				b.Fatal(err)
			}
		}
	}
}

func loadBenchmarkLines(b *testing.B) ([][]byte, int) {
	b.Helper()

	path := os.Getenv("BENCH_FILE")
	if path == "" {
		return generatedBenchmarkLines()
	} else if !filepath.IsAbs(path) {
		path = filepath.Join("../..", path)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		b.Fatal(err)
	}

	rawLines := bytes.Split(bytes.TrimSpace(data), []byte("\n"))
	lines := make([][]byte, 0, len(rawLines))
	totalBytes := 0
	for _, line := range rawLines {
		line = bytes.TrimSpace(line)
		if len(line) == 0 {
			continue
		}
		lines = append(lines, line)
		totalBytes += len(line)
	}
	if len(lines) == 0 {
		b.Fatalf("benchmark file has no JSON lines: %s", path)
	}
	return lines, totalBytes
}

func generatedBenchmarkLines() ([][]byte, int) {
	lines := make([][]byte, 0, 256)
	totalBytes := 0
	for i := 0; i < 256; i++ {
		line := []byte(fmt.Sprintf(
			`{"$active_feature_flags":"[\"beta-%d\"]","$exception_types":"undefined","Account.client_id":"client_%d","huge":18446744073709551616,"duplicate":"","duplicate":"kept","nested":{"a.b":{"c":%d}}}`,
			i,
			i,
			i,
		))
		lines = append(lines, line)
		totalBytes += len(line)
	}
	return lines, totalBytes
}

func TestProcessLineSplitsTemporaryProperties(t *testing.T) {
	tests := []struct {
		name, input, permanent, temporary string
	}{
		{
			name:      "allowlist",
			input:     `{"$set":{"score":7,"enabled":false},"$set_once":{"source":"demo"},"$unset":["old"],"$group_set":{"tier":"basic"},"$feature_flag_request_id":"request-example","$debug_first_full_snapshot_timestamp":1,"$snapshot_max_depth_exceeded":true,"$sess_rec_flush_size":2,"$session_recording_remote_config":{"enabled":true},"$session_recording_network_payload_capture":false,"$session_recording_canvas_recording":true,"$replay_script_config":{"version":3},"$sent_at":"2026-01-01","$lib_rate_limit_remaining_tokens":0,"$lib_custom_api_host":"https://example.com","$sdk_debug_new_metric":[[1,"x"],null],"$sdk_debug_current_session_duration":42,"$debug_images":[{"type":"elf"}],"$feature/demo":"control","$active_feature_flags":["demo"],"$feature_flag_payload":{},"$feature_flag_payloads":{},"$feature_flag_bootstrapped_payload":{},"$feature_flag_original_payload":{},"$transformations_succeeded":[],"custom":{"$set":"keep"}}`,
			permanent: `{"$debug_images":[{"type":"elf"}],"custom":{"$set":"keep"},"$feature_flags":{"demo":"control"}}`,
			temporary: `{"$set":{"score":7,"enabled":false},"$set_once":{"source":"demo"},"$unset":["old"],"$group_set":{"tier":"basic"},"$feature_flag_request_id":"request-example","$debug_first_full_snapshot_timestamp":1,"$snapshot_max_depth_exceeded":true,"$sess_rec_flush_size":2,"$session_recording_remote_config":{"enabled":true},"$session_recording_network_payload_capture":false,"$session_recording_canvas_recording":true,"$replay_script_config":{"version":3},"$sent_at":"2026-01-01","$lib_rate_limit_remaining_tokens":0,"$lib_custom_api_host":"https://example.com","$sdk_debug_new_metric":[[1,"x"],null],"$sdk_debug_current_session_duration":42}`,
		},
		{
			name:      "dotted roots and normalization",
			input:     `{"$set.profile.score":7,"$set.profile.missing":null,"$sdk_debug_probe.a":1,"$sdk_debug_probe.a":2,"$sdk_debug_probe.large":18446744073709551616,"$sdk_debug_current_session_duration.value":42,"$set_extra":true,"$debug_custom":"keep","custom.$set":"keep"}`,
			permanent: `{"$set_extra":true,"$debug_custom":"keep","custom":{"$set":"keep"}}`,
			temporary: `{"$set":{"profile":{"score":7}},"$sdk_debug_probe":{"a":1,"large":"18446744073709551616"},"$sdk_debug_current_session_duration":{"value":42}}`,
		},
		{
			name: "nothing temporary", input: `{"custom":true}`, permanent: `{"custom":true}`, temporary: `{}`,
		},
		{
			name: "already separated", input: `{"$set":{"enabled":false},"$unset":[]}`, permanent: `{}`, temporary: `{"$set":{"enabled":false},"$unset":[]}`,
		},
	}
	for _, kind := range []propertiesKind{eventProperties, temporaryProperties} {
		temporaryOnly := kind == temporaryProperties
		proc := processor{kind: kind}
		var got bytes.Buffer
		for _, tt := range tests {
			t.Run(fmt.Sprintf("%s/temporary=%t", tt.name, temporaryOnly), func(t *testing.T) {
				want := tt.permanent
				if temporaryOnly {
					want = tt.temporary
				}
				if err := proc.processLine([]byte(tt.input), &got); err != nil {
					t.Fatal(err)
				}
				if got.String() != want {
					t.Fatalf("got %s, want %s", got.String(), want)
				}
			})
		}
	}
	for _, input := range []string{`{"broken"`, `[]`, `null`, `"text"`} {
		proc := processor{kind: temporaryProperties}
		var got bytes.Buffer
		if err := proc.processLine([]byte(input), &got); err == nil {
			t.Fatalf("expected error for temporary properties %s", input)
		}
	}
}
