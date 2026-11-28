import type { TimeRange } from '../dashboard/document/dashboardTypes'

/**
 * A rule-based NRQL → HogQL translator for the common shapes of a New Relic dashboard query:
 *
 *     SELECT count(*) | uniqueCount(x) | sum(x) | average(x) | percentile(x, N) | filter(agg, WHERE …) | percentage(…)
 *     FROM Event [WHERE …] [FACET a, b] [LIMIT n] [SINCE n units ago] [UNTIL …] [TIMESERIES [n unit | AUTO]]
 *
 * An event type becomes `event = '<Event>'` and an attribute becomes `properties.<attr>`. The time range comes from the
 * board through `{filters}`. Anything outside these rules fails with a reason, so the importer can keep the original
 * query on the tile instead of guessing.
 */

export interface NrqlTranslation {
    ok: true
    hogql: string
    /** One query per SELECT column, for charts that draw only the first number of a query. Set when it has several. */
    hogqlPerColumn?: string[]
    timeseries: boolean
    /** The time range its SINCE and UNTIL ask for, when they can be written as a board time range. */
    since?: TimeRange
    events: string[]
    properties: string[]
    notes: string[]
}

export interface NrqlFailure {
    ok: false
    reason: string
    events: string[]
}

class NrqlError extends Error {}

interface Token {
    kind: 'string' | 'number' | 'ident' | 'quoted' | 'op'
    text: string
}

const TOKEN =
    /\s+|('(?:''|\\.|[^'\\])*')|(\d+(?:\.\d+)?)|([A-Za-z_][\w.]*)|(`[^`]*`)|(<=|>=|!=|<>|[=<>+\-*/(),])|(\S)/gy

function tokenize(nrql: string): Token[] {
    const tokens: Token[] = []
    for (const match of nrql.matchAll(TOKEN)) {
        const [, string, number, ident, quoted, op, other] = match
        if (other !== undefined) {
            throw new NrqlError(`It has the character "${other}", which the translator doesn't read.`)
        }
        if (string !== undefined) {
            tokens.push({ kind: 'string', text: string })
        } else if (number !== undefined) {
            tokens.push({ kind: 'number', text: number })
        } else if (ident !== undefined) {
            tokens.push({ kind: 'ident', text: ident })
        } else if (quoted !== undefined) {
            tokens.push({ kind: 'quoted', text: quoted.slice(1, -1) })
        } else if (op !== undefined) {
            tokens.push({ kind: 'op', text: op })
        }
    }
    return tokens
}

const CLAUSES = new Set([
    'SELECT',
    'FROM',
    'WHERE',
    'FACET',
    'SINCE',
    'UNTIL',
    'TIMESERIES',
    'LIMIT',
    'COMPARE',
    'WITH',
    'EXTRAPOLATE',
    'SLIDE',
    'ORDER',
    'OFFSET',
    'JOIN',
])
const UNSUPPORTED_CLAUSES: Record<string, string> = {
    COMPARE: 'COMPARE WITH',
    SLIDE: 'SLIDE BY',
    ORDER: 'ORDER BY',
    OFFSET: 'OFFSET',
    JOIN: 'JOIN',
}
const NON_EVENT_SOURCES: Record<string, string> = {
    Metric: 'New Relic metrics',
    Log: 'New Relic logs',
    Span: 'New Relic traces',
}

const upper = (token: Token | undefined): string => (token?.kind === 'ident' ? token.text.toUpperCase() : '')

function splitClauses(tokens: Token[]): Map<string, Token[]> {
    const clauses = new Map<string, Token[]>()
    let current: Token[] | undefined
    let depth = 0
    let previous = ''
    for (const token of tokens) {
        depth += token.text === '(' ? 1 : token.text === ')' ? -1 : 0
        const keyword = upper(token)
        if (depth === 0 && CLAUSES.has(keyword) && !(keyword === 'WITH' && previous === 'COMPARE')) {
            if (clauses.has(keyword)) {
                throw new NrqlError(`It has more than one ${keyword}.`)
            }
            current = []
            clauses.set(keyword, current)
            previous = keyword
            continue
        }
        if (!current) {
            throw new NrqlError("It doesn't start with SELECT or FROM.")
        }
        current.push(token)
    }
    return clauses
}

function splitList(tokens: Token[]): Token[][] {
    const items: Token[][] = [[]]
    let depth = 0
    for (const token of tokens) {
        depth += token.text === '(' ? 1 : token.text === ')' ? -1 : 0
        if (depth === 0 && token.text === ',') {
            items.push([])
        } else {
            items[items.length - 1].push(token)
        }
    }
    return items.filter((item) => item.length > 0)
}

const UNITS: Record<string, { since: string; interval: string; seconds: number }> = {
    SECOND: { since: 's', interval: 'Second', seconds: 1 },
    MINUTE: { since: 'm', interval: 'Minute', seconds: 60 },
    HOUR: { since: 'h', interval: 'Hour', seconds: 3600 },
    DAY: { since: 'd', interval: 'Day', seconds: 86400 },
    WEEK: { since: 'w', interval: 'Week', seconds: 604800 },
    MONTH: { since: 'M', interval: 'Month', seconds: 2592000 },
}
export const own = <T>(record: Record<string, T>, key: string): T | undefined =>
    Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined
const unitOf = (token: Token | undefined): (typeof UNITS)[string] | undefined =>
    own(UNITS, upper(token).replace(/S$/, ''))

function relativeTime(tokens: Token[]): { end: string; seconds: number } | undefined {
    if (tokens.length === 1 && upper(tokens[0]) === 'NOW') {
        return { end: 'now', seconds: 0 }
    }
    const unit = unitOf(tokens[1])
    if (tokens.length !== 3 || tokens[0].kind !== 'number' || !unit || upper(tokens[2]) !== 'AGO') {
        return undefined
    }
    const amount = Number(tokens[0].text)
    return Number.isInteger(amount) ? { end: `now-${amount}${unit.since}`, seconds: amount * unit.seconds } : undefined
}

/** A plain identifier needs no quoting. Others, such as `request.uri`, read as one property name in backticks. */
function hogqlName(name: string): string {
    return /^[A-Za-z_]\w*$/.test(name) ? name : `\`${name.replace(/`/g, '\\`')}\``
}

const AGGREGATES: Record<string, (arg: string, cond?: string) => string> = {
    count: (arg, cond) =>
        arg === '*'
            ? cond
                ? `countIf(${cond})`
                : 'count()'
            : cond
              ? `countIf(isNotNull(${arg}) and (${cond}))`
              : `count(${arg})`,
    uniquecount: (arg, cond) => (cond ? `uniqExactIf(${arg}, ${cond})` : `uniqExact(${arg})`),
    sum: (arg, cond) => (cond ? `sumIf(toFloat(${arg}), ${cond})` : `sum(toFloat(${arg}))`),
    average: (arg, cond) => (cond ? `avgIf(toFloat(${arg}), ${cond})` : `avg(toFloat(${arg}))`),
    max: (arg, cond) => (cond ? `maxIf(toFloat(${arg}), ${cond})` : `max(toFloat(${arg}))`),
    min: (arg, cond) => (cond ? `minIf(toFloat(${arg}), ${cond})` : `min(toFloat(${arg}))`),
    median: (arg, cond) => (cond ? `quantileIf(0.5)(toFloat(${arg}), ${cond})` : `quantile(0.5)(toFloat(${arg}))`),
    stddev: (arg, cond) => (cond ? `stddevPopIf(toFloat(${arg}), ${cond})` : `stddevPop(toFloat(${arg}))`),
    latest: (arg, cond) => (cond ? `argMaxIf(${arg}, timestamp, ${cond})` : `argMax(${arg}, timestamp)`),
    earliest: (arg, cond) => (cond ? `argMinIf(${arg}, timestamp, ${cond})` : `argMin(${arg}, timestamp)`),
}
AGGREGATES.avg = AGGREGATES.average

interface Column {
    sql: string
    alias: string
}

class Translator {
    properties = new Set<string>()

    property(name: string): string {
        if (name === 'timestamp') {
            return 'timestamp'
        }
        this.properties.add(name)
        return `properties.${hogqlName(name)}`
    }

    /**
     * An attribute inside an aggregate or a FACET, such as `duration`, `duration / 60`, `eventType()` or `lower(name)`.
     */
    attribute(tokens: Token[]): string {
        if (tokens.length === 1 && tokens[0].text === '*') {
            return '*'
        }
        const numeric = tokens.some((token) => ['+', '-', '*', '/'].includes(token.text))
        let sql = ''
        for (let index = 0; index < tokens.length; index++) {
            const token = tokens[index]
            const call =
                token.kind === 'ident' && tokens[index + 1]?.text === '(' ? token.text.toLowerCase() : undefined
            if (call === 'eventtype' && tokens[index + 2]?.text === ')') {
                sql += 'event'
                index += 2
            } else if ((call === 'lower' || call === 'upper') && tokens[index + 3]?.text === ')' && !numeric) {
                sql += `${call}(toString(${this.attribute([tokens[index + 2]])}))`
                index += 3
            } else if (call) {
                throw new NrqlError(`It uses ${token.text}(), which the translator can't turn into SQL yet.`)
            } else if (token.kind === 'ident' || token.kind === 'quoted') {
                const property = this.property(token.text)
                sql += numeric ? `toFloat(${property})` : property
            } else if (token.kind === 'number' || (numeric && ['+', '-', '*', '/', '(', ')'].includes(token.text))) {
                sql += ['+', '-', '*', '/'].includes(token.text) ? ` ${token.text} ` : token.text
            } else {
                throw new NrqlError(`The translator can't read "${token.text}" here.`)
            }
        }
        if (!sql) {
            throw new NrqlError('An aggregate or FACET is empty.')
        }
        return sql
    }

    /** `cases(WHERE a AS 'x', WHERE b AS 'y')`, as one label per event. Events that match no case get null, and are left out. */
    cases(args: Token[]): string {
        const branches = splitList(args).map((item) => {
            const { tokens, alias } = aliasOf(item)
            if (upper(tokens[0]) !== 'WHERE') {
                throw new NrqlError('Each case in cases() needs a WHERE condition.')
            }
            const condition = this.condition(tokens.slice(1))
            return `${condition}, ${quote(alias ?? condition)}`
        })
        return `multiIf(${branches.join(', ')}, null)`
    }

    /** One SELECT item: aggregates and arithmetic between them, such as `sum(a) / count(*)`. */
    selectItem(tokens: Token[], cond?: string): string {
        let index = 0
        const peek = (): Token | undefined => tokens[index]
        const argsUntilClose = (): Token[] => {
            const start = index
            let depth = 1
            for (; index < tokens.length; index++) {
                depth += tokens[index].text === '(' ? 1 : tokens[index].text === ')' ? -1 : 0
                if (depth === 0) {
                    return tokens.slice(start, index++)
                }
            }
            throw new NrqlError('A parenthesis is never closed.')
        }
        const factor = (): string => {
            const token = peek()
            if (!token) {
                throw new NrqlError('A SELECT item ends early.')
            }
            index++
            if (token.kind === 'number') {
                return token.text
            }
            if (token.text === '-') {
                return `-${factor()}`
            }
            if (token.text === '(') {
                const inner = this.selectItem(argsUntilClose(), cond)
                return `(${inner})`
            }
            if (token.kind === 'ident' && peek()?.text === '(') {
                index++
                return this.call(token.text, argsUntilClose(), cond)
            }
            throw new NrqlError(
                token.kind === 'ident' || token.kind === 'quoted'
                    ? `It selects ${token.text} without an aggregate, which lists raw events.`
                    : `The translator can't read "${token.text}" in a SELECT item.`
            )
        }
        const term = (): string => {
            let sql = factor()
            while (peek()?.text === '*' || peek()?.text === '/') {
                const op = peek()!.text
                index++
                sql = `${sql} ${op} ${factor()}`
            }
            return sql
        }
        let sql = term()
        while (peek()?.text === '+' || peek()?.text === '-') {
            const op = peek()!.text
            index++
            sql = `${sql} ${op} ${term()}`
        }
        if (index < tokens.length) {
            throw new NrqlError(`The translator can't read "${tokens[index].text}" in a SELECT item.`)
        }
        return sql
    }

    call(name: string, args: Token[], cond?: string): string {
        const lowered = name.toLowerCase()
        const parts = splitList(args)
        if (lowered === 'filter' || lowered === 'percentage') {
            const where = parts[1]
            if (parts.length !== 2 || upper(where[0]) !== 'WHERE') {
                throw new NrqlError(`${name}() needs an aggregate and a WHERE condition.`)
            }
            const condition = this.condition(where.slice(1))
            const both = cond ? `(${cond}) and (${condition})` : condition
            const filtered = this.selectItem(parts[0], both)
            return lowered === 'filter' ? filtered : `((${filtered}) / (${this.selectItem(parts[0], cond)}) * 100)`
        }
        if (lowered === 'percentile') {
            if (parts.length !== 2 || parts[1].length !== 1 || parts[1][0].kind !== 'number') {
                throw new NrqlError('percentile() with more than one percentile needs one column each.')
            }
            const level = Number(parts[1][0].text) / 100
            const arg = this.attribute(parts[0])
            return cond ? `quantileIf(${level})(toFloat(${arg}), ${cond})` : `quantile(${level})(toFloat(${arg}))`
        }
        const aggregate = own(AGGREGATES, lowered)
        if (!aggregate || parts.length !== 1) {
            throw new NrqlError(`It uses ${name}(), which the translator can't turn into SQL yet.`)
        }
        return aggregate(this.attribute(parts[0]), cond)
    }

    condition(tokens: Token[]): string {
        let index = 0
        const peek = (): Token | undefined => tokens[index]
        const keyword = (...words: string[]): boolean => {
            if (words.every((word, offset) => upper(tokens[index + offset]) === word)) {
                index += words.length
                return true
            }
            return false
        }
        const literal = (): Token => {
            const token = peek()
            if (
                !token ||
                (token.kind !== 'string' && token.kind !== 'number' && !/^(TRUE|FALSE)$/.test(upper(token)))
            ) {
                throw new NrqlError(`The translator can't read "${token?.text ?? 'the end'}" as a value in WHERE.`)
            }
            index++
            return token
        }
        const valueSql = (token: Token): string => (token.kind === 'ident' ? token.text.toLowerCase() : token.text)
        const operand = (): string => {
            const token = peek()
            if (upper(token) === 'EVENTTYPE' && tokens[index + 1]?.text === '(' && tokens[index + 2]?.text === ')') {
                index += 3
                return 'event'
            }
            if (token?.kind === 'ident' && tokens[index + 1]?.text === '(') {
                throw new NrqlError(`It uses ${token.text}() in WHERE, which the translator can't turn into SQL yet.`)
            }
            if (token?.kind !== 'ident' && token?.kind !== 'quoted') {
                throw new NrqlError(`The translator can't read "${token?.text ?? 'the end'}" in WHERE.`)
            }
            index++
            return this.property(token.text)
        }
        const predicate = (): string => {
            if (peek()?.text === '(') {
                index++
                const start = index
                let depth = 1
                for (; index < tokens.length && depth > 0; index++) {
                    depth += tokens[index].text === '(' ? 1 : tokens[index].text === ')' ? -1 : 0
                }
                return `(${this.condition(tokens.slice(start, index - 1))})`
            }
            const left = operand()
            if (keyword('IS', 'NOT', 'NULL')) {
                return `isNotNull(${left})`
            }
            if (keyword('IS', 'NULL')) {
                return `isNull(${left})`
            }
            if (keyword('IS', 'TRUE')) {
                return `${left} = true`
            }
            if (keyword('IS', 'FALSE')) {
                return `${left} = false`
            }
            const negated = keyword('NOT')
            if (keyword('IN')) {
                if (peek()?.text !== '(') {
                    throw new NrqlError('IN needs a list of values.')
                }
                index++
                if (upper(peek()) === 'SELECT') {
                    throw new NrqlError("It uses a subquery, which the translator can't turn into SQL yet.")
                }
                const values: string[] = []
                while (peek() && peek()!.text !== ')') {
                    values.push(valueSql(literal()))
                    if (peek()?.text === ',') {
                        index++
                    }
                }
                index++
                return `${left} ${negated ? 'not in' : 'in'} (${values.join(', ')})`
            }
            if (keyword('LIKE')) {
                // NRQL's LIKE ignores case.
                return `${left} ${negated ? 'not ilike' : 'ilike'} ${literal().text}`
            }
            if (keyword('RLIKE')) {
                return `${negated ? 'not ' : ''}match(toString(${left}), ${literal().text})`
            }
            if (negated) {
                throw new NrqlError('NOT is only read before IN, LIKE or a condition.')
            }
            const op = peek()
            if (!op || !['=', '!=', '<>', '<', '>', '<=', '>='].includes(op.text)) {
                throw new NrqlError(`The translator can't read "${op?.text ?? 'the end'}" after ${left} in WHERE.`)
            }
            index++
            const value = literal()
            const numeric = value.kind === 'number' && op.text !== '=' && op.text !== '!=' && op.text !== '<>'
            return `${numeric ? `toFloat(${left})` : left} ${op.text === '<>' ? '!=' : op.text} ${valueSql(value)}`
        }
        const not = (): string => (keyword('NOT') ? `not ${not()}` : predicate())
        const and = (): string => {
            let sql = not()
            while (keyword('AND')) {
                sql = `${sql} and ${not()}`
            }
            return sql
        }
        let sql = and()
        while (keyword('OR')) {
            sql = `${sql} or ${and()}`
        }
        if (index < tokens.length) {
            throw new NrqlError(`The translator can't read "${tokens[index].text}" in WHERE.`)
        }
        return sql
    }
}

function aliasOf(item: Token[]): { tokens: Token[]; alias?: string } {
    const at = item.length - 2
    if (at > 0 && upper(item[at]) === 'AS') {
        const name = item[at + 1]
        return {
            tokens: item.slice(0, at),
            alias: name.kind === 'string' ? name.text.slice(1, -1).replace(/''/g, "'") : name.text,
        }
    }
    return { tokens: item }
}

// HogQL refuses some characters in identifiers, such as `%` and `$`.
function columnAlias(name: string, used: Set<string>): string {
    const readable =
        name
            .replace(/%/g, ' percent')
            .replace(/[^\w .-]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim() || 'value'
    let alias = readable
    for (let n = 2; used.has(alias); n++) {
        alias = `${readable}_${n}`
    }
    used.add(alias)
    return hogqlName(alias)
}

function bucketFor(tokens: Token[], sinceSeconds: number | undefined): string {
    const unit = unitOf(tokens[1]) ?? unitOf(tokens[0])
    if (unit && (tokens.length === 2 || tokens.length === 1)) {
        const amount = tokens.length === 2 ? Number(tokens[0].text) : 1
        if (Number.isInteger(amount) && amount > 0) {
            return `toStartOfInterval(timestamp, toInterval${unit.interval}(${amount}))`
        }
    }
    if (tokens.length > 1 || (tokens.length === 1 && !/^(AUTO|MAX)$/.test(upper(tokens[0])))) {
        throw new NrqlError("Its TIMESERIES interval has a form the translator doesn't read.")
    }
    // New Relic picks the bucket from the range, so this does the same for the range the query asks for.
    if (sinceSeconds !== undefined && sinceSeconds <= 6 * 3600) {
        return 'toStartOfInterval(timestamp, toIntervalMinute(5))'
    }
    return sinceSeconds !== undefined && sinceSeconds > 3 * 86400
        ? 'toStartOfDay(timestamp)'
        : 'toStartOfHour(timestamp)'
}

// New Relic's default number of facets.
const DEFAULT_FACET_LIMIT = 10
const MAX_FACET_LIMIT = 100

export function translateNrql(nrql: string): NrqlTranslation | NrqlFailure {
    const events: string[] = []
    try {
        const clauses = splitClauses(tokenize(nrql.trim().replace(/;$/, '')))
        const from = clauses.get('FROM') ?? []
        for (const item of splitList(from)) {
            if (item.length !== 1 || (item[0].kind !== 'ident' && item[0].kind !== 'quoted')) {
                throw new NrqlError('Its FROM is a subquery or expression, not an event type.')
            }
            events.push(item[0].text)
        }
        for (const [clause, name] of Object.entries(UNSUPPORTED_CLAUSES)) {
            if (clauses.has(clause)) {
                throw new NrqlError(`It uses ${name}, which the translator can't turn into SQL yet.`)
            }
        }
        if (events.length === 0 || !clauses.has('SELECT')) {
            throw new NrqlError('It needs a SELECT and a FROM.')
        }
        const source = events.find((event) => own(NON_EVENT_SOURCES, event))
        if (source) {
            events.length = 0
            throw new NrqlError(`It reads ${NON_EVENT_SOURCES[source]}, which aren't events in PostHog.`)
        }
        const notes: string[] = []
        const withClause = clauses.get('WITH')
        if (withClause) {
            if (upper(withClause[0]) !== 'TIMEZONE') {
                throw new NrqlError(
                    `It uses WITH ${withClause[0]?.text ?? ''}, which the translator can't turn into SQL yet.`
                )
            }
            notes.push("Its timezone isn't kept. Boards show times in the project's timezone.")
        }
        if (clauses.has('EXTRAPOLATE')) {
            notes.push("EXTRAPOLATE isn't needed: PostHog counts every event.")
        }

        const translator = new Translator()
        const sinceTokens = clauses.get('SINCE')
        const untilTokens = clauses.get('UNTIL')
        const since = sinceTokens ? relativeTime(sinceTokens) : undefined
        const until = untilTokens ? relativeTime(untilTokens) : undefined
        if ((sinceTokens && !since) || (untilTokens && !until)) {
            notes.push("Its SINCE or UNTIL isn't a relative time, so it uses the board's time range.")
        }

        const timeseriesTokens = clauses.get('TIMESERIES')
        const timeseries = timeseriesTokens !== undefined
        // The time bucket is always `time`, so no column or facet may take that name.
        const used = new Set<string>(timeseries ? ['time'] : [])
        const columns: Column[] = []
        for (const item of splitList(clauses.get('SELECT') ?? [])) {
            const { tokens, alias } = aliasOf(item)
            const multi =
                upper(tokens[0]) === 'PERCENTILE' && tokens[1]?.text === '(' && tokens[tokens.length - 1]?.text === ')'
                    ? splitList(tokens.slice(2, -1))
                    : undefined
            if (multi && multi.length > 2 && !alias) {
                for (const level of multi.slice(1)) {
                    const sql = translator.call('percentile', [...multi[0], { kind: 'op', text: ',' }, ...level])
                    columns.push({ sql, alias: columnAlias(`p${level.map((t) => t.text).join('')}`, used) })
                }
                continue
            }
            const sql = translator.selectItem(tokens)
            const fallback = upper(tokens[0]).toLowerCase().replace('uniquecount', 'unique') || 'value'
            columns.push({ sql, alias: columnAlias(alias ?? fallback, used) })
        }
        if (columns.length === 0) {
            throw new NrqlError('Its SELECT is empty.')
        }

        const facets = splitList(clauses.get('FACET') ?? []).map((facet) => {
            const { tokens, alias } = aliasOf(facet)
            const isCases =
                upper(tokens[0]) === 'CASES' && tokens[1]?.text === '(' && tokens[tokens.length - 1]?.text === ')'
            const sql = isCases ? translator.cases(tokens.slice(2, -1)) : translator.attribute(tokens)
            if (sql === '*') {
                throw new NrqlError("It facets by *, which the translator can't read.")
            }
            const name =
                alias ?? (isCases || tokens[1]?.text === '(' ? 'facet' : tokens[0].text.split('.').pop() || 'facet')
            return { sql, alias: columnAlias(name, used), isCases }
        })

        const eventFilter =
            events.length === 1 ? `event = ${quote(events[0])}` : `event in (${events.map(quote).join(', ')})`
        const where = clauses.get('WHERE')
        const matchesACase = facets.filter((facet) => facet.isCases).map((facet) => ` and isNotNull(${facet.sql})`)
        const scope = `${eventFilter}${where ? ` and (${translator.condition(where)})` : ''}${matchesACase.join('')} and {filters}`
        const limitToken = clauses.get('LIMIT')?.[0]
        const limit =
            upper(limitToken) === 'MAX'
                ? MAX_FACET_LIMIT
                : limitToken?.kind === 'number'
                  ? Math.min(MAX_FACET_LIMIT, Number(limitToken.text))
                  : DEFAULT_FACET_LIMIT

        const select = columns.map((column) => `${column.sql} as ${column.alias}`)
        const facetSelect = facets.map((facet) => `${facet.sql} as ${facet.alias}`)
        const facetAliases = facets.map((facet) => facet.alias)
        let hogql: string
        let hogqlPerColumn: string[] | undefined
        if (timeseries) {
            const bucket = bucketFor(
                timeseriesTokens,
                since && since.seconds > 0 ? since.seconds - (until?.seconds ?? 0) : undefined
            )
            const groups = ['time', ...facetAliases]
            let topFacets = ''
            if (facets.length > 0) {
                const key = facets.length === 1 ? facets[0].sql : `(${facets.map((facet) => facet.sql).join(', ')})`
                const keys = facets.map((facet) => facet.sql).join(', ')
                // New Relic ranks facets by the first SELECT item.
                topFacets = ` and ${key} in (select ${keys} from events where ${scope} group by ${keys} order by ${columns[0].sql} desc limit ${limit})`
            }
            const query = (selected: string[]): string =>
                `select ${[`${bucket} as time`, ...facetSelect, ...selected].join(', ')} from events ` +
                `where ${scope}${topFacets} group by ${groups.join(', ')} order by time`
            hogql = query(select)
            hogqlPerColumn = select.length > 1 ? select.map((one) => query([one])) : undefined
        } else if (facets.length > 0) {
            hogql =
                `select ${[...facetSelect, ...select].join(', ')} from events where ${scope} ` +
                `group by ${facetAliases.join(', ')} order by ${columns[0].alias} desc limit ${limit}`
        } else {
            hogql = `select ${select.join(', ')} from events where ${scope}`
        }
        return {
            ok: true,
            hogql,
            ...(hogqlPerColumn ? { hogqlPerColumn } : {}),
            timeseries,
            ...(since && since.end !== 'now' ? { since: { from: since.end, to: until?.end ?? 'now' } } : {}),
            events,
            properties: [...translator.properties],
            notes,
        }
    } catch (error) {
        if (error instanceof NrqlError) {
            return { ok: false, reason: error.message, events }
        }
        throw error
    }
}

function quote(value: string): string {
    return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}
