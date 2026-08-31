package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestProcessLineCleansEventProperties(t *testing.T) {
	input := []byte(`{"$active_feature_flags":"undefined","$active_feature_flags":["beta",42,null,{"a.b":1}],"Account.client_id":"abc","Account":{"client_id":null},"huge":18446744073709551616,"max_uint":18446744073709551615,"too_negative":-9223372036854775809,"min_int":-9223372036854775808,"null_field":null,"dupe":"","dupe":"kept","emptydupe":"","emptydupe":null}`)
	want := `{"Account":{"client_id":"abc"},"huge":"18446744073709551616","max_uint":18446744073709551615,"too_negative":"-9223372036854775809","min_int":-9223372036854775808,"dupe":"kept","emptydupe":""}`

	var got bytes.Buffer
	if err := processLine(input, &got); err != nil {
		t.Fatal(err)
	}
	if got.String() != want {
		t.Fatalf("processLine() = %s, want %s", got.String(), want)
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

func TestProcessLineGroupsFeatureProperties(t *testing.T) {
	input := []byte(`{"$feature/first-flag":"control","$feature/number":42,"$feature/enabled":true,"$feature/config":{"nested.value":"dropped"},"$feature_flags":"invalid","$feature_flags":{"existing":"kept"},"$feature_flag_payloads":{"flag":"dropped"},"other":"value"}`)
	want := `{"$feature_flags":{"existing":"kept","first-flag":"control","number":42,"enabled":true,"config":{"nested":{"value":"dropped"}}},"other":"value"}`

	var got bytes.Buffer
	if err := processLine(input, &got); err != nil {
		t.Fatal(err)
	}
	if got.String() != want {
		t.Fatalf("processLine() = %s, want %s", got.String(), want)
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
		`{"$properties_unparsable":"spoofed","$exception_list":"[redacted]","kept":"value"}`: `{"$exception_list":[],"kept":"value","$properties_unparsable":"{\"$exception_list\":\"[redacted]\"}"}`,
		`{"$exception_list":[1]}`:  `{"$exception_list":[],"$properties_unparsable":"{\"$exception_list\":[1]}"}`,
		`{"$exception_list":true}`: `{"$exception_list":[],"$properties_unparsable":"{\"$exception_list\":true}"}`,
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
	parsed, err := proc.parseValue()
	if err != nil {
		t.Fatal(err)
	}
	cleaned, err := proc.cleanNode(makePathRules("outer.$exception_sources"), parsed)
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
	var got bytes.Buffer
	if err := processLine([]byte(`{"broken"`), &got); err == nil {
		t.Fatal("expected error for malformed JSON, got nil")
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
