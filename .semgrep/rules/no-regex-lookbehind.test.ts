// @ts-nocheck
// Test fixture for no-regex-lookbehind rule.

// ruleid: no-regex-lookbehind
const positiveLookbehind = /(?<=\|)x/

// ruleid: no-regex-lookbehind
const negativeLookbehind = /(?<!\\),/

// ruleid: no-regex-lookbehind
const namedGroup = /(?<year>\d{4})-(?<month>\d{2})/

// ok: no-regex-lookbehind
const lookahead = /foo(?=bar)/

// ok: no-regex-lookbehind
const negativeLookahead = /foo(?!bar)/

// ok: no-regex-lookbehind
const plain = /^\|(?:\s*:?-{2,}:?\s*\|)+\s*$/

// ok: no-regex-lookbehind
const backreference = /(\w+)\1/

// A lookbehind escaped into a literal (matches the text `(?<`, not an assertion) is safe.
// ok: no-regex-lookbehind
const escapedLiteral = /(?:^|[^\\])\(\?<[=!]/

// Mentions of (?<=x) and (?<!x) in comments or strings must not be flagged.
// ok: no-regex-lookbehind
const message = 'Lookbehind assertions ((?<=test), (?<!test)) are not supported.'

// ok: no-regex-lookbehind
const division = totalCount / windowSize
