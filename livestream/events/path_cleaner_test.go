package events

import (
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestPathCleanerClean(t *testing.T) {
	tests := []struct {
		name  string
		rules string
		path  string
		want  string
	}{
		{
			name:  "id segment collapses to alias",
			rules: `[{"alias": "/classes/:id", "regex": "/classes/[^/]+"}]`,
			path:  "/classes/928q3hr9paw8hfe",
			want:  "/classes/:id",
		},
		{
			name:  "backreference expands the captured group",
			rules: `[{"alias": "/item/\\1", "regex": "/item/(\\d+)-.*"}]`,
			path:  "/item/42-blue-widget",
			want:  "/item/42",
		},
		{
			name:  "digit after a backreference stays literal, not group 10",
			rules: `[{"alias": "/v\\10/x", "regex": "/version/(\\d)"}]`,
			path:  "/version/7",
			want:  "/v70/x",
		},
		{
			name:  "dollar sign in alias stays literal",
			rules: `[{"alias": "/$price", "regex": "/cost/.*"}]`,
			path:  "/cost/123",
			want:  "/$price",
		},
		{
			name:  "escaped backslash in alias is one literal backslash",
			rules: `[{"alias": "/a\\\\b", "regex": "/raw/.*"}]`,
			path:  "/raw/x",
			want:  `/a\b`,
		},
		{
			name:  "rules chain in list order, each fed the previous output",
			rules: `[{"alias": "/classes/:id", "regex": "/classes/[^/]+"}, {"alias": "/c/:id", "regex": "/classes/:id"}]`,
			path:  "/classes/abc123",
			want:  "/c/:id",
		},
		{
			name:  "invalid regex is skipped, later rules still apply",
			rules: `[{"alias": "x", "regex": "("}, {"alias": "/classes/:id", "regex": "/classes/[^/]+"}]`,
			path:  "/classes/abc123",
			want:  "/classes/:id",
		},
		{
			name:  "inline re2 flags work",
			rules: `[{"alias": "/docs", "regex": "(?i)/DOCS/.*"}]`,
			path:  "/docs/setup",
			want:  "/docs",
		},
		{
			name:  "missing alias replaces with empty string",
			rules: `[{"regex": "/classes/[^/]+"}]`,
			path:  "/classes/abc123",
			want:  "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cleaner := NewPathCleanerFromJSON(tt.rules)
			require.NotNil(t, cleaner)
			assert.Equal(t, tt.want, cleaner.Clean(tt.path))
		})
	}
}

func TestNewPathCleanerFromJSONReturnsNilWhenNothingApplies(t *testing.T) {
	for name, raw := range map[string]string{
		"empty string":       "",
		"whitespace":         "   ",
		"not json":           "not-json",
		"empty array":        "[]",
		"only invalid rules": `[{"alias": "x", "regex": "("}, {"alias": "y", "regex": ""}]`,
	} {
		t.Run(name, func(t *testing.T) {
			assert.Nil(t, NewPathCleanerFromJSON(raw))
		})
	}
}

func TestPathCleanerBoundsOutputAmplification(t *testing.T) {
	// A `(.) -> \1\1` rule doubles the path, and rules chain each fed the
	// previous output, so enough of them would grow a short path past any memory
	// limit. Cleaning must bail and return the raw path instead of amplifying
	// unbounded in the shared fan-out loop. Without the size cap this Clean call
	// allocates gigabytes and never returns.
	// 14 doublings of a 4-char path cross the ceiling at rule 12, so cleaning
	// bails there. Kept just past the bail point: if the cap regresses, the
	// fallback is a 64 KiB string that fails the assert cleanly, not a multi-
	// terabyte allocation that OOMs the runner.
	doubling := `{"alias": "\\1\\1", "regex": "(.)"}`
	rules := "[" + strings.Repeat(doubling+",", 13) + doubling + "]"
	cleaner := NewPathCleanerFromJSON(rules)
	require.NotNil(t, cleaner)

	path := "/abc"
	got := cleaner.Clean(path)
	assert.Equal(t, path, got, "amplifying ruleset must fall back to the raw path")
	assert.LessOrEqual(t, len(got), maxCleanedPathLen)
}

func TestPathCleanerReturnsOversizedInputUnchanged(t *testing.T) {
	cleaner := NewPathCleanerFromJSON(`[{"alias": "/x", "regex": "/.*"}]`)
	require.NotNil(t, cleaner)

	path := "/" + strings.Repeat("a", maxCleanedPathLen)
	assert.Equal(t, path, cleaner.Clean(path), "a path over the ceiling must skip cleaning, not run rules on it")
}

func TestPathCleanerSkipsOverlongAlias(t *testing.T) {
	longAlias := strings.Repeat("x", maxPathCleaningAliasLen+1)
	// The over-long alias rule is dropped; the valid rule after it still applies.
	rules := fmt.Sprintf(`[{"alias": %q, "regex": "/a/.*"}, {"alias": "/b", "regex": "/a/.*"}]`, longAlias)
	cleaner := NewPathCleanerFromJSON(rules)
	require.NotNil(t, cleaner)

	assert.Equal(t, "/b", cleaner.Clean("/a/123"))
}

func TestConvertInjectsCleanedPathnameWithoutMutatingSharedEvent(t *testing.T) {
	cleaner := NewPathCleanerFromJSON(`[{"alias": "/classes/:id", "regex": "/classes/[^/]+"}]`)
	require.NotNil(t, cleaner)

	event := PostHogEvent{
		Uuid:       "uuid-1",
		DistinctId: "user-1",
		Event:      "$pageview",
		Properties: map[string]interface{}{"$pathname": "/classes/928q3hr9paw8hfe"},
	}

	// columns == nil normally aliases the shared event map; the cleaner must
	// copy so its per-subscriber property never leaks into other subscriptions.
	response := convertToResponsePostHogEvent(event, 1, nil, cleaner)
	assert.Equal(t, "/classes/:id", response.Properties["$virt_cleaned_pathname"])
	assert.Equal(t, "/classes/928q3hr9paw8hfe", response.Properties["$pathname"])
	assert.NotContains(t, event.Properties, "$virt_cleaned_pathname")

	// With a column allowlist the property is injected after filtering, so
	// subscribers don't need to request it explicitly.
	withColumns := convertToResponsePostHogEvent(event, 1, []string{"$pathname"}, cleaner)
	assert.Equal(t, "/classes/:id", withColumns.Properties["$virt_cleaned_pathname"])

	// No cleaner, no property.
	withoutCleaner := convertToResponsePostHogEvent(event, 1, nil, nil)
	assert.NotContains(t, withoutCleaner.Properties, "$virt_cleaned_pathname")
}
