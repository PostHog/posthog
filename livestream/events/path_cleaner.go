package events

import (
	"encoding/json"
	"log"
	"regexp"
	"strings"
)

// Bounds on subscriber-supplied rules, so one subscription can't compile
// unbounded regex work into the event fan-out loop.
const (
	maxPathCleaningRules    = 100
	maxPathCleaningRegexLen = 1000
)

type pathCleaningRule struct {
	regex       *regexp.Regexp
	replacement string
}

// PathCleaner applies a team's path cleaning rules the way ClickHouse's
// chained replaceRegexpAll calls do: every rule in list order, each fed the
// previous rule's output. Go's regexp is RE2, the same engine ClickHouse
// uses, so results match the query-side cleaning exactly.
type PathCleaner struct {
	rules []pathCleaningRule
}

// NewPathCleanerFromJSON parses a JSON array of {alias, regex, order} rules,
// the wire shape of team.path_cleaning_filters. Returns nil when there is
// nothing to apply. Rules that don't compile are skipped, matching how the
// query side skips rules that fail validation.
func NewPathCleanerFromJSON(raw string) *PathCleaner {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil
	}
	var payloads []struct {
		Alias *string `json:"alias"`
		Regex *string `json:"regex"`
	}
	if err := json.Unmarshal([]byte(raw), &payloads); err != nil {
		log.Printf("WARNING: ignoring unparseable pathCleaning rules: %v", err)
		return nil
	}
	if len(payloads) > maxPathCleaningRules {
		payloads = payloads[:maxPathCleaningRules]
	}

	rules := make([]pathCleaningRule, 0, len(payloads))
	for _, p := range payloads {
		if p.Regex == nil || *p.Regex == "" || len(*p.Regex) > maxPathCleaningRegexLen {
			continue
		}
		re, err := regexp.Compile(*p.Regex)
		if err != nil {
			log.Printf("WARNING: ignoring invalid path cleaning regex %q: %v", *p.Regex, err)
			continue
		}
		alias := ""
		if p.Alias != nil {
			alias = *p.Alias
		}
		rules = append(rules, pathCleaningRule{regex: re, replacement: translateAlias(alias)})
	}
	if len(rules) == 0 {
		return nil
	}
	return &PathCleaner{rules: rules}
}

func (pc *PathCleaner) Clean(path string) string {
	for _, rule := range pc.rules {
		path = rule.regex.ReplaceAllString(path, rule.replacement)
	}
	return path
}

// translateAlias converts a replaceRegexpAll replacement string (`\0`-`\9`
// backreferences, `\\` literal backslash, everything else literal) into Go's
// ReplaceAllString syntax. Backreferences become `${N}` rather than `$N` so a
// digit following the reference stays literal, and literal `$` becomes `$$`
// so Go never reads it as an expansion.
func translateAlias(alias string) string {
	var b strings.Builder
	for i := 0; i < len(alias); i++ {
		ch := alias[i]
		switch {
		case ch == '\\' && i+1 < len(alias) && alias[i+1] == '\\':
			b.WriteByte('\\')
			i++
		case ch == '\\' && i+1 < len(alias) && alias[i+1] >= '0' && alias[i+1] <= '9':
			b.WriteString("${")
			b.WriteByte(alias[i+1])
			b.WriteByte('}')
			i++
		case ch == '$':
			b.WriteString("$$")
		default:
			b.WriteByte(ch)
		}
	}
	return b.String()
}
