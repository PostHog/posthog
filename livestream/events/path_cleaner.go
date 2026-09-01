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
	maxPathCleaningAliasLen = 1000
	// Ceiling on the working path while cleaning. A rule can amplify output (a
	// `(.) -> \1\1` rule doubles the string) and rules chain each fed the
	// previous output, so N of them grow it 2^N. Bailing once the path passes a
	// size no real $pathname reaches keeps one subscription from exhausting
	// memory/CPU in the shared fan-out loop.
	maxCleanedPathLen = 8 * 1024
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
		// A long alias packed with backreferences amplifies each match, so cap
		// it alongside the regex. Without this a single rule could still blow the
		// path up in one pass.
		if len(alias) > maxPathCleaningAliasLen {
			continue
		}
		rules = append(rules, pathCleaningRule{regex: re, replacement: translateAlias(alias)})
	}
	if len(rules) == 0 {
		return nil
	}
	return &PathCleaner{rules: rules}
}

func (pc *PathCleaner) Clean(path string) string {
	// Cleaning is best-effort normalization: if the raw path already exceeds the
	// ceiling, or a rule amplifies it past one, abandon cleaning and return the
	// raw path rather than let an abusive ruleset grow it unbounded. Bounding each
	// rule's output also caps the next rule's input, so the chain can't compound.
	if len(path) > maxCleanedPathLen {
		return path
	}
	cleaned := path
	for _, rule := range pc.rules {
		// Size the result from the match and group lengths before running the
		// replacement, so a rule that would amplify the path bails here instead of
		// letting ReplaceAllString allocate the whole blown-up string first. The
		// replacement itself stays stdlib, so cleaned output matches the query side
		// exactly.
		if replacementOverflows(rule.regex, rule.replacement, cleaned) {
			return path
		}
		cleaned = rule.regex.ReplaceAllString(cleaned, rule.replacement)
	}
	return cleaned
}

// replacementOverflows reports whether applying the rule to src would produce
// more than maxCleanedPathLen bytes, computed from match offsets and group
// lengths without building the (possibly amplified) result. `replacement` is
// translateAlias output: `${0}`-`${9}` backreferences, `$$` for a literal `$`,
// everything else literal — so the byte count matches what ReplaceAllString
// would emit.
func replacementOverflows(re *regexp.Regexp, replacement, src string) bool {
	total := 0
	last := 0
	for _, m := range re.FindAllStringSubmatchIndex(src, -1) {
		total += m[0] - last
		last = m[1]
		for i := 0; i < len(replacement); i++ {
			c := replacement[i]
			if c == '$' && i+1 < len(replacement) {
				if replacement[i+1] == '$' {
					total++
					i++
					continue
				}
				if replacement[i+1] == '{' && i+3 < len(replacement) &&
					replacement[i+2] >= '0' && replacement[i+2] <= '9' && replacement[i+3] == '}' {
					if g := int(replacement[i+2] - '0'); 2*g+1 < len(m) && m[2*g] >= 0 {
						total += m[2*g+1] - m[2*g]
					}
					i += 3
					continue
				}
			}
			total++
		}
		if total > maxCleanedPathLen {
			return true
		}
	}
	return total+(len(src)-last) > maxCleanedPathLen
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
