/**
 * Small PromQL and LogQL text tools for the importers. Not a parser: it knows strings, identifiers, selectors and
 * brackets, which is enough to find metric names and make the few edits an import needs without touching the rest.
 * The rules match the metrics product's importer (`products/metrics/backend/dashboard_import/promql_text.py`).
 */

const TOKEN =
    /(\s+|#[^\n]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`[^`]*`)|((?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[a-zA-Z]*)|([a-zA-Z_:][a-zA-Z0-9_:]*)|(\$\{[^}]*\}|\$[a-zA-Z_]\w*|\[\[\w+\]\])|(=~|!~|!=|==|>=|<=|.)/gs

type TokenKind = 'space' | 'string' | 'number' | 'ident' | 'variable' | 'punct'
interface Token {
    kind: TokenKind
    text: string
    start: number
    end: number
}

const KINDS: TokenKind[] = ['space', 'string', 'number', 'ident', 'variable', 'punct']

function tokenize(expr: string): Token[] {
    return [...expr.matchAll(TOKEN)].map((match) => ({
        kind: KINDS[match.slice(1).findIndex((group) => group !== undefined)],
        text: match[0],
        start: match.index,
        end: match.index + match[0].length,
    }))
}

const AGGREGATORS = new Set([
    'sum',
    'avg',
    'count',
    'min',
    'max',
    'stddev',
    'stdvar',
    'topk',
    'bottomk',
    'quantile',
    'count_values',
    'group',
    'limitk',
])
const GROUPING = new Set(['by', 'without', 'on', 'ignoring', 'group_left', 'group_right'])
const KEYWORDS = new Set([...GROUPING, 'bool', 'and', 'or', 'unless', 'offset', 'atan2', 'inf', 'nan'])

export function promqlMetrics(expr: string): string[] {
    const tokens = tokenize(expr).filter((token) => token.kind !== 'space')
    const names: string[] = []
    let skipDepth = 0
    for (let index = 0; index < tokens.length; index++) {
        const token = tokens[index]
        if (token.kind === 'punct' && (token.text === '{' || token.text === '[')) {
            skipDepth++
            continue
        }
        if (
            token.text === '__name__' &&
            tokens[index + 1]?.text === '=' &&
            tokens[index + 2]?.kind === 'string' &&
            tokens[index + 2].text.length > 2
        ) {
            names.push(tokens[index + 2].text.slice(1, -1))
            index += 2
            continue
        }
        if (token.kind === 'punct' && (token.text === '}' || token.text === ']')) {
            skipDepth = Math.max(0, skipDepth - 1)
            continue
        }
        if (skipDepth > 0 || token.kind !== 'ident') {
            continue
        }
        const calls = tokens[index + 1]?.text === '('
        const lowered = token.text.toLowerCase()
        if (GROUPING.has(lowered) && calls) {
            // The label list of `by (...)` holds labels, not metrics.
            let depth = 0
            for (index++; index < tokens.length; index++) {
                depth += tokens[index].text === '(' ? 1 : tokens[index].text === ')' ? -1 : 0
                if (depth === 0) {
                    break
                }
            }
            continue
        }
        if (!calls && !AGGREGATORS.has(lowered) && !KEYWORDS.has(lowered)) {
            names.push(token.text)
        }
    }
    return [...new Set(names)]
}

const STEP_WINDOW = /^\$\{?__(rate_interval|interval|auto)\}?$/

/**
 * Removes `[$__rate_interval]` and `[$__interval]` windows. Grafana fills these per panel; PostHog's PromQL runner
 * reads a range function without a window over the query step, which is what they stand for.
 */
export function stripStepWindows(expr: string): string {
    const tokens = tokenize(expr)
    let out = ''
    let kept = 0
    let open = -1
    for (let index = 0; index < tokens.length; index++) {
        if (tokens[index].text === '[') {
            open = index
        } else if (tokens[index].text === ']' && open >= 0) {
            const inner = expr.slice(tokens[open].end, tokens[index].start).trim()
            if (STEP_WINDOW.test(inner)) {
                out += expr.slice(kept, tokens[open].start)
                kept = tokens[index].end
            }
            open = -1
        }
    }
    return out + expr.slice(kept)
}

/**
 * LogQL needs a window on every range function, so Grafana's per-panel windows become a fixed one. Returns the text and
 * whether any window was replaced, so the report can say the tile may differ.
 */
export function fixLogqlWindows(expr: string, window: string): { text: string; replaced: boolean } {
    let replaced = false
    const text = expr.replace(/\[\s*(\$\{?__(?:rate_interval|interval|auto|range)\}?)\s*\]/g, () => {
        replaced = true
        return `[${window}]`
    })
    return { text, replaced }
}

const VARIABLE_REFERENCE = /\$\{(\w+)(?::\w+)?\}|\$(\w+)|\[\[(\w+)\]\]/g

export function fillVariables(expr: string, values: Map<string, string>): { text: string; unfilled: string[] } {
    const unfilled = new Set<string>()
    const text = expr.replace(VARIABLE_REFERENCE, (match, braced?: string, bare?: string, old?: string) => {
        const name = braced ?? bare ?? old ?? ''
        if (name.startsWith('__')) {
            return match
        }
        const value = values.get(name)
        if (value === undefined) {
            unfilled.add(name)
            return match
        }
        return value
    })
    return { text, unfilled: [...unfilled] }
}

/**
 * MetricsQL functions Grafana boards on VictoriaMetrics use that PromQL has no equivalent for. They go as written,
 * since PostHog's engine runs some of them; the report names them so a person can check the tile.
 */
const METRICSQL_ONLY = new Set([
    'quantiles',
    'histogram_quantiles',
    'range_quantile',
    'range_median',
    'range_avg',
    'range_max',
    'range_min',
    'range_sum',
    'running_sum',
    'running_avg',
    'keep_last_value',
    'label_set',
    'label_del',
    'label_keep',
    'limit_offset',
    'union',
    'aggr_over_time',
    'rollup',
    'rollup_rate',
    'share_le_over_time',
    'share_gt_over_time',
    'count_le_over_time',
    'median_over_time',
    'distinct_over_time',
    'increase_pure',
    'outliersk',
])

export function metricsqlFunctions(expr: string): string[] {
    const tokens = tokenize(expr).filter((token) => token.kind !== 'space')
    const found = tokens
        .filter((token, index) => token.kind === 'ident' && tokens[index + 1]?.text === '(')
        .map((token) => token.text.toLowerCase())
        .filter((name) => METRICSQL_ONLY.has(name))
    return [...new Set(found)]
}

// A selector, with any quoted values inside it, so a label matcher such as `status!="200"` isn't read as a line filter.
const SELECTOR = /\{(?:[^{}"`]|"(?:\\.|[^"\\])*"|`[^`]*`)*\}/g

export function looksLikeLogql(expr: string): boolean {
    const outside = expr.replace(SELECTOR, '{}')
    return /\|=|\|~|(!=|!~)\s*["`]|\|\s*(json|logfmt|line_format|pattern|regexp|unwrap)\b|(count|bytes|rate)_over_time\s*\(\s*\{/.test(
        outside
    )
}

const LOKI_LABELS: Record<string, string> = {
    namespace: 'k8s.namespace.name',
    pod: 'k8s.pod.name',
    container: 'k8s.container.name',
    node: 'k8s.node.name',
    cluster: 'k8s.cluster.name',
    app: 'service_name',
    service: 'service_name',
}

// String literals come first in each pattern, so a line filter such as `|= "by (pod)"` is kept as written.
const STRING_LITERAL = '"(?:\\\\.|[^"\\\\])*"|`[^`]*`'

export function rewriteLogql(expr: string): string {
    const to = (label: string): string => LOKI_LABELS[label] ?? label
    return expr
        .replace(
            new RegExp(`(${STRING_LITERAL})|\\{([^{}"]*(?:"(?:[^"\\\\]|\\\\.)*"[^{}"]*)*)\\}`, 'g'),
            (match, literal: string | undefined, body: string) =>
                literal !== undefined || !/^\s*[A-Za-z_]\w*\s*(=~|!~|!=|=)/.test(body)
                    ? match
                    : `{${body.replace(
                          /(^|,)(\s*)([A-Za-z_]\w*)(\s*)(?==~|!~|!=|=)/g,
                          (_m, sep: string, space: string, label: string, after: string) =>
                              `${sep}${space}${to(label)}${after}`
                      )}}`
        )
        .replace(
            new RegExp(`(${STRING_LITERAL})|\\b(by|without)\\s*\\(([^)]*)\\)`, 'g'),
            (match, literal: string | undefined, keyword: string, list: string) =>
                literal !== undefined
                    ? match
                    : `${keyword} (${list
                          .split(',')
                          .map((label) => to(label.trim()))
                          .filter(Boolean)
                          .join(', ')})`
        )
}

export function logqlLegend(legend: string): string {
    return legend.replace(/\{\{\s*(\w+)\s*\}\}/g, (match, label: string) =>
        LOKI_LABELS[label] ? `{{${LOKI_LABELS[label]}}}` : match
    )
}

export function logqlStreams(expr: string): string[] {
    return [...new Set(expr.match(/\{[^{}]*\}/g) ?? [])]
}
