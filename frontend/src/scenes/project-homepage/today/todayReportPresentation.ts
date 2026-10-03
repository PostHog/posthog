import { Dayjs, dayjs } from 'lib/dayjs'
import { colonDelimitedDuration, reverseColonDelimitedDuration } from 'lib/utils/durations'
import { isObject } from 'lib/utils/guards'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { ReportMetricApi, SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'
import { selectReportCardImpactMetric } from 'products/signals/frontend/inbox/components/cards/ReportCardImpactMetric'
import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { reportMetricRowParts, reportMetricWindowLabel } from 'products/signals/frontend/inbox/utils/reportMetrics'
import { safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'
import { primaryReportPullRequest } from 'products/signals/frontend/inbox/utils/reportPullRequests'
import { parseReportSummary } from 'products/signals/frontend/inbox/utils/reportSummary'
import { conversationsTicketUrl, genericSignalLink } from 'products/signals/frontend/inbox/utils/signalLinks'

export interface TodayReportImpact {
    metric: ReportMetricApi
    value: string
    unit: string
    title: string
    window: string | null
}

export interface TodayReportSections {
    lead: string
    impact: string | null
    proposal: string | null
    expected: string | null
}

export type TodaySignalDestination =
    | { kind: 'recording'; sessionId: string; timestamp: number | null; offset: string | null }
    | { kind: 'link'; to: string; external: boolean; label: string }
    | { kind: 'read' }

export type TodayNextStep =
    | { kind: 'review_pr'; url: string; state: 'draft' | 'open'; reviewDecision: string | null; byTask: boolean }
    | { kind: 'merged'; url: string }
    | { kind: 'task_running'; since: string | null }
    | { kind: 'claimed'; by: string; since: string | null }
    | { kind: 'already_addressed' }
    | { kind: 'needs_input' }
    | { kind: 'start' }

const PARAGRAPH_HEADING = /^\*\*([^*\n]+?):?\*\*:?\s*$/
const PROPOSAL_HEADINGS = new Set([
    'solution',
    'the solution',
    'fix',
    'the fix',
    'proposed fix',
    'recommended fix',
    'suggested fix',
    'smallest fix',
    'recommendation',
    'recommendations',
    'recommended action',
    'recommended next step',
    'recommended next steps',
    'next step',
    'next steps',
])
const EXPECTED_HEADINGS = new Set(['expected impact', 'expected behavior', 'expected result'])
const IMPACT_HEADINGS = new Set(['impact'])
const CHART_REFERENCE = /\[([^\]]+)\]\(chart:[^)]*\)/g
const BOILERPLATE_LINES = [
    /^new error tracking issue created\b/i,
    /^this error tracking issue is experiencing a spike\b/i,
    /^\(baseline:/i,
    /^-{3,}$/,
    /^(exception|uuid|commit sha|feature|type|value|filename):/i,
    /^anomaly investigation for alert\b/i,
    /^verdict changed from\b/i,
    /^insight:/i,
    /^\[(info|warning|critical)\]/i,
]
const SLACK_LINK = /https?:\/\/[\w.-]*slack\.com\/\S+/i
const REPO_FILE_ID = /^([\w.-]+\/[\w.-]+):([^\s:]+)$/
const HEADING_WORD_LIMIT = 6

function withoutChartReferences(markdown: string): string {
    return markdown
        .replace(/(?<=[.!?])\s*\[[^\]]+\]\(chart:[^)]*\)\.?(?=\s*$|\n)/gm, '')
        .replace(CHART_REFERENCE, '$1')
        .trim()
}

function paragraphs(markdown: string): string[] {
    return markdown
        .split(/\n\s*\n/)
        .map((paragraph) => paragraph.trim())
        .filter(Boolean)
}

function joinSections(parts: (string | null | undefined)[]): string | null {
    const text = parts
        .filter((part): part is string => !!part && part.trim().length > 0)
        .map((part) => withoutChartReferences(part))
        .join('\n\n')
    return text || null
}

function isParagraphHeading(line: string): string | null {
    const match = line.trim().match(PARAGRAPH_HEADING)
    if (!match) {
        return null
    }
    const heading = match[1].trim()
    if (/[.!?]$/.test(heading) || heading.split(/\s+/).length > HEADING_WORD_LIMIT) {
        return null
    }
    return heading
}

function splitParagraphHeadings(markdown: string): { lead: string; sections: { heading: string; body: string }[] } {
    const sections: { heading: string; lines: string[] }[] = []
    const leadLines: string[] = []
    let current = leadLines
    for (const line of markdown.split('\n')) {
        const heading = isParagraphHeading(line)
        if (heading) {
            const section = { heading, lines: [] }
            sections.push(section)
            current = section.lines
            continue
        }
        current.push(line)
    }
    return {
        lead: leadLines.join('\n').trim(),
        sections: sections.map((section) => ({ heading: section.heading, body: section.lines.join('\n').trim() })),
    }
}

export function todayReportSections(summary: string | null | undefined): TodayReportSections {
    const parsed = parseReportSummary(summary)
    if (parsed.sections.length > 0) {
        const [lead] = paragraphs(parsed.lead)
        const find = (kind: string): string | null =>
            parsed.sections.find((section) => section.kind === kind)?.body ?? null
        return {
            lead: withoutChartReferences(lead ?? ''),
            impact: joinSections([find('impact')]),
            proposal: joinSections([find('solution')]),
            expected: joinSections([find('expected-impact')]),
        }
    }
    const split = splitParagraphHeadings(parsed.lead)
    const [lead] = paragraphs(split.lead)
    const pick = (names: Set<string>): string | null =>
        split.sections.find((section) => names.has(section.heading.toLowerCase()) && section.body)?.body ?? null
    return {
        lead: withoutChartReferences(lead ?? ''),
        impact: joinSections([pick(IMPACT_HEADINGS)]),
        proposal: joinSections([pick(PROPOSAL_HEADINGS)]),
        expected: joinSections([pick(EXPECTED_HEADINGS)]),
    }
}

export function todayReportImpact(report: Pick<SignalReport, 'metrics'>): TodayReportImpact | null {
    const metric = selectReportCardImpactMetric(report.metrics)
    const parts = metric ? reportMetricRowParts(metric, metric.value) : null
    if (!metric || !parts) {
        return null
    }
    return {
        metric,
        value: parts.value,
        unit: parts.unit.trim(),
        title: metric.title.trim().replace(/\.$/, ''),
        window: reportMetricWindowLabel(metric.query),
    }
}

export interface TodayDailyTrend {
    data: number[]
    since: string | null
    /** The first day of `data` as an ISO date, when the series is daily. */
    start: string | null
}

export function dailyTrend(metric: Pick<ReportMetricApi, 'series' | 'value_at' | 'query'>): TodayDailyTrend | null {
    const series = metric.series ?? []
    if (series.length < 2 || series.some((point) => !Number.isFinite(point))) {
        return null
    }
    const query = isObject(metric.query) ? (metric.query as { source?: { interval?: unknown } }) : {}
    const first = series.findIndex((point) => point > 0)
    if (query.source?.interval !== 'day' || !metric.value_at || first <= 0) {
        return { data: series, since: null, start: null }
    }
    const start = dayjs(metric.value_at).subtract(series.length - 1 - first, 'day')
    return { data: series.slice(first), since: start.format('D MMM'), start: start.format('YYYY-MM-DD') }
}

export function todayNextStep(
    report: SignalReport,
    context: { taskRunning: boolean; slotClaimed: boolean }
): TodayNextStep {
    const pullRequest = primaryReportPullRequest(report)
    const url = safeHttpUrl(pullRequest.url ?? '')
    if (url && pullRequest.merged) {
        return { kind: 'merged', url }
    }
    if (url && pullRequest.state !== 'closed') {
        return {
            kind: 'review_pr',
            url,
            state: pullRequest.state === 'draft' ? 'draft' : 'open',
            reviewDecision: pullRequest.review_decision ?? null,
            byTask: report.assignee?.kind === 'task',
        }
    }
    const assignee = report.assignee ?? null
    if (context.taskRunning || context.slotClaimed || assignee?.kind === 'task') {
        return { kind: 'task_running', since: assignee?.claimed_at ?? null }
    }
    if (assignee?.kind === 'user' || assignee?.kind === 'agent') {
        const user = assignee.user
        const name = user ? [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email : null
        return { kind: 'claimed', by: name ?? assignee.agent ?? 'an agent', since: assignee.claimed_at ?? null }
    }
    if (report.already_addressed) {
        return { kind: 'already_addressed' }
    }
    if (report.status === 'pending_input') {
        return { kind: 'needs_input' }
    }
    return { kind: 'start' }
}

const SENTENCE_BREAK = /(?<=[.!?])\s+(?=[A-Z0-9"“(*`])/

const BARE_GITHUB_LINK = /(?<![(<[])https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/(?:pull|issues)\/(\d+)(?![\w/])/g

export function shortenGitHubLinks(markdown: string): string {
    return markdown.replace(BARE_GITHUB_LINK, (url, number) => `[#${number}](${url})`)
}

const GITHUB_PULL_URL = /https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/(\d+)/g

const BARE_PULL_REFERENCE = /\bPR #(\d+)\b/g

/** The one pull request a text names, by URL or, when the repository is known, as "PR #123". */
/** The pull requests a text names, by number, with their URLs. */
export function pullRequestsIn(text: string | null | undefined, repoSlug?: string | null): Map<string, string> {
    const pulls = new Map([...(text ?? '').matchAll(GITHUB_PULL_URL)].map((match) => [match[1], match[0]]))
    if (pulls.size === 0 && repoSlug) {
        for (const match of (text ?? '').matchAll(BARE_PULL_REFERENCE)) {
            pulls.set(match[1], `https://github.com/${repoSlug}/pull/${match[1]}`)
        }
    }
    return pulls
}

export function onlyPullRequest(
    text: string | null | undefined,
    repoSlug?: string | null
): { url: string; number: string } | null {
    const pulls = pullRequestsIn(text, repoSlug)
    if (pulls.size !== 1) {
        return null
    }
    const [[number, url]] = [...pulls.entries()]
    return { url, number }
}

/** The pull request a report's fix is in: the one its proposal names, else the only one it names at all. */
export function inFlightPullRequest(
    report: Pick<SignalReport, 'summary' | 'repo_slug'>
): { url: string; number: string } | null {
    return (
        onlyPullRequest(todayReportSections(report.summary).proposal, report.repo_slug) ??
        onlyPullRequest(report.summary, report.repo_slug)
    )
}

const LIST_MARKER = /^\s*(?:[-*+]|\d+[.)])\s+/

function balanced(text: string, marker: string): string {
    return text.split(marker).length % 2 === 0 ? `${text}${marker}` : text
}

function shownLength(markdown: string): number {
    return inlineSegments(markdown).reduce((length, segment) => length + segment.text.length, 0)
}

export function conciseText(markdown: string | null | undefined, maxChars: number): string {
    const sentences = (markdown ?? '')
        .split(/\n+/)
        .map((line) => line.replace(LIST_MARKER, '').trim())
        .filter(Boolean)
        .map((line) => (/[.!?:]$/.test(line) ? line : `${line}.`))
        .flatMap((line) => line.split(SENTENCE_BREAK))
        .map((sentence) => sentence.trim())
        .filter(Boolean)
    let text = ''
    for (const sentence of sentences) {
        const next = text ? `${text} ${sentence}` : sentence
        if (text && shownLength(next) > maxChars) {
            break
        }
        text = next
    }
    return balanced(balanced(text, '**'), '`')
}

export function distinctEvidenceCount(signals: SignalNodeApi[]): number {
    return new Set(signals.map((signal) => `${signal.source_product}:${signal.source_id}`)).size
}

const CODE_PATH = /`[^`]*[/.][^`]*`/

export function mentionsCodePath(markdown: string): boolean {
    return CODE_PATH.test(markdown)
}

function evidenceItem(signal: SignalNodeApi): string {
    const alert = signal.source_product === 'analytics' ? stringField(extraOf(signal), 'alert_id') : null
    return alert ? `analytics:alert:${alert}` : `${signal.source_product}:${signal.source_id}`
}

export function pickEvidence(signals: SignalNodeApi[], count: number): SignalNodeApi[] {
    const newestFirst = [...signals].sort(
        (first, second) => new Date(second.timestamp).getTime() - new Date(first.timestamp).getTime()
    )
    const items = new Set<string>()
    const unique = newestFirst.filter((signal) => {
        const item = evidenceItem(signal)
        return !items.has(item) && !!items.add(item)
    })
    const sources = new Set<string>()
    const leads = unique.filter((signal) => !sources.has(signal.source_product) && !!sources.add(signal.source_product))
    const rest = unique.filter((signal) => !leads.includes(signal))
    const byDate = (first: SignalNodeApi, second: SignalNodeApi): number =>
        new Date(second.timestamp).getTime() - new Date(first.timestamp).getTime()
    return [...leads, ...rest].slice(0, count).sort(byDate)
}

export function priorityBadgeVariant(priority: string | null | undefined): 'destructive' | 'warning' | 'default' {
    if (priority === 'P0' || priority === 'P1') {
        return 'destructive'
    }
    if (priority === 'P2') {
        return 'warning'
    }
    return 'default'
}

const PROPER_WORDS: Record<string, string> = {
    ai: 'AI',
    api: 'API',
    github: 'GitHub',
    llm: 'LLM',
    mcp: 'MCP',
    posthog: 'PostHog',
    pr: 'PR',
    sql: 'SQL',
    ui: 'UI',
    ux: 'UX',
}

export function scoutLabel(skillName: string | null | undefined): string | null {
    if (!skillName) {
        return null
    }
    const name = skillName
        .replace(/^signals-scout-/, '')
        .replace(/\bself-driving\b/g, 'self\u2011driving')
        .replace(/[-_]+/g, ' ')
        .replace(/\u2011/g, '-')
        .trim()
        .split(' ')
        .map((word) => PROPER_WORDS[word.toLowerCase()] ?? word)
        .join(' ')
    return name ? `${name.charAt(0).toUpperCase()}${name.slice(1)} scout` : null
}

function plainLine(line: string): string {
    return line
        .replace(/^C:\s*/, '')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/(?:slack (?:reply|thread|message)|thread|link):\s*https?:\/\/\S+/gi, '')
        .replace(/\s*\(\s*https?:\/\/[^\s)]+\s*\)/g, '')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/`([^`]+)`/g, (_, code: string) => (/\s/.test(code) ? `“${code}”` : code))
        .replace(/[`*]/g, '')
        .replace(/\\([.#()[\]_*-])/g, '$1')
        .replace(/\s+/g, ' ')
        .replace(/\s+([.,;:])/g, '$1')
        .trim()
}

const SENTENCE_END = /[.!?](?=\s+[A-Z“"(])/g
const MIN_SENTENCE_CHARS = 40

function insideQuote(text: string): boolean {
    const opened = (text.match(/“/g) ?? []).length - (text.match(/”/g) ?? []).length
    return opened > 0 || (text.match(/"/g) ?? []).length % 2 === 1
}

/** The first sentence, never cut inside a quotation. */
function firstSentence(text: string): string {
    for (const match of text.matchAll(SENTENCE_END)) {
        const end = (match.index ?? 0) + 1
        if (end >= MIN_SENTENCE_CHARS && !insideQuote(text.slice(0, end))) {
            return text.slice(0, end)
        }
    }
    return text
}

function extraOf(signal: Pick<SignalNodeApi, 'extra'>): Record<string, unknown> {
    return isObject(signal.extra) ? (signal.extra as Record<string, unknown>) : {}
}

function stringField(extra: Record<string, unknown>, key: string): string | null {
    const value = extra[key]
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

const ISO_DATE = /\b(\d{4}-\d{2}-\d{2})\b/g

function readableDates(text: string): string {
    return text.replace(ISO_DATE, (match) => {
        const date = dayjs(match)
        return date.isValid() ? date.format('D MMM') : match
    })
}

const MONTH_DAY = /(?<=\bon )(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b/g
const BARE_INTEGER = /(?<![\w#.,/:-])(?:\d{5,7}|(?!19|20)\d{4}(?= [a-z]))(?![\w/:-]|[.,]\d)/g

/** Quoted research reads like the page: dates as "10 Sep" and large counts with thousands separators. */
export function readableExcerpt(text: string): string {
    return readableDates(text)
        .replace(
            MONTH_DAY,
            (_, month: string, day: string) =>
                `${Number(day)} ${dayjs()
                    .month(Number(month) - 1)
                    .format('MMM')}`
        )
        .replace(BARE_INTEGER, (match) => Number(match).toLocaleString('en-US'))
}

const HEADLINE_CHARS = 170
// A clause break wins over a word break only when it keeps most of the sentence's room.
const MIN_CLAUSE_CHARS = 130

const QUOTE_MARK = /“|”|(?<=^|\s)["']|["'](?=[\s.,;:!?]|$)/g

/** Where an opening quotation mark that the text never closes starts, or -1. */
function unclosedQuoteStart(text: string): number {
    let open = -1
    for (const match of text.matchAll(QUOTE_MARK)) {
        const index = match.index ?? 0
        const opening = match[0] === '“' || (match[0] !== '”' && (index === 0 || /\s/.test(text[index - 1])))
        open = opening ? index : -1
    }
    return open
}

const TRAILING_PUNCTUATION = /[\s,;:–—-]+$/
const DANGLING_WORDS = new Set([
    'a',
    'an',
    'the',
    'and',
    'or',
    'but',
    'so',
    'with',
    'to',
    'of',
    'in',
    'on',
    'for',
    'by',
    'at',
    'from',
    'as',
    'into',
    'via',
    'than',
    'that',
    'which',
    'who',
])

function withoutDanglingWords(text: string): string {
    const words = text.split(' ')
    while (words.length > 1 && DANGLING_WORDS.has(words[words.length - 1].toLowerCase())) {
        words.pop()
    }
    return words.join(' ')
}

/** Shortens text at the last clause or word that fits, so a two-line clamp never has to cut a word. */
function fitHeadline(text: string): string {
    if (text.length <= HEADLINE_CHARS) {
        return text
    }
    const window = text.slice(0, HEADLINE_CHARS)
    const clause = Math.max(window.lastIndexOf(', '), window.lastIndexOf('; '))
    const wordEnd = clause >= MIN_CLAUSE_CHARS ? clause : window.lastIndexOf(' ')
    const cut = text.slice(0, wordEnd > 0 ? wordEnd : HEADLINE_CHARS)
    const quoteStart = unclosedQuoteStart(cut)
    const body = quoteStart > MIN_CLAUSE_CHARS / 2 ? cut.slice(0, quoteStart) : cut
    return `${withoutDanglingWords(body.replace(TRAILING_PUNCTUATION, '')).replace(TRAILING_PUNCTUATION, '')}…`
}

export function signalHeadline(signal: Pick<SignalNodeApi, 'content'>): string {
    const withoutCode = signal.content.replace(/```[\s\S]*?(```|$)/g, '\n')
    for (const raw of withoutCode.split('\n')) {
        const line = plainLine(raw)
        if (!line || BOILERPLATE_LINES.some((pattern) => pattern.test(line))) {
            continue
        }
        return fitHeadline(readableExcerpt(firstSentence(line)))
    }
    return fitHeadline(readableExcerpt(plainLine(signal.content))) || 'Signal'
}

export interface TodaySignalReading {
    /** The opening sentence in full, where the row's headline may be shortened. */
    lead: string
    /** The rest of the signal's text, without the boilerplate lines a source adds. */
    rest: string
    /** Short facts about where the signal came from, such as the scout or the database server. */
    facts: string[]
}

const LINK_POINTER_WORDS = 6

/** Drops sentences that only point at a link, such as "The thread is available at <url>", since the row links there itself. */
function withoutLinkPointers(line: string): string {
    return line
        .split(SENTENCE_BREAK)
        .filter((sentence) => {
            const rest = sentence.replace(/https?:\/\/\S+/g, '').trim()
            return rest === sentence.trim() || rest.split(/\s+/).length > LINK_POINTER_WORDS
        })
        .join(' ')
}

/** What an evidence row shows once it is opened. */
export function signalReading(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'content' | 'extra'>
): TodaySignalReading {
    const lines = signal.content
        .replace(/```[\s\S]*?(```|$)/g, '\n')
        .split('\n')
        .map((line) => plainLine(withoutLinkPointers(line)))
        .filter((line) => line && !BOILERPLATE_LINES.some((pattern) => pattern.test(line)))
    const text = lines.map((line) => (/[.!?:)]$/.test(line) ? line : `${line}.`)).join(' ')
    const lead = firstSentence(text)
    const extra = extraOf(signal)
    const skill = stringField(extra, 'skill_name')
    const facts = [
        signal.source_product === 'signals_scout' ? scoutLabel(skill) : null,
        signal.source_product === 'pganalyze' ? stringField(extra, 'server_name') : null,
        signal.source_product === 'pganalyze' && stringField(extra, 'severity')
            ? `${stringField(extra, 'severity')} severity`
            : null,
        ...signalMetaParts(signal),
    ].filter((fact): fact is string => !!fact)
    return {
        lead: readableExcerpt(lead || plainLine(signal.content)),
        rest: readableExcerpt(text.slice(lead.length).trim()),
        facts,
    }
}

function isPullRequest(signal: Pick<SignalNodeApi, 'source_type' | 'extra'>): boolean {
    const extra = extraOf(signal)
    return /pull/i.test(signal.source_type) || typeof extra.pull_request === 'object' || 'merged_at' in extra
}

export function signalMetaParts(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'extra'>
): string[] {
    const extra = extraOf(signal)
    const parts: (string | null)[] = []
    switch (signal.source_product) {
        case 'github': {
            const number = typeof extra.number === 'number' ? `#${extra.number}` : null
            parts.push(number ? `${isPullRequest(signal) ? 'Pull request' : 'Issue'} ${number}` : null)
            break
        }
        case 'conversations':
        case 'zendesk': {
            parts.push(typeof extra.ticket_number === 'number' ? `Ticket #${extra.ticket_number}` : null)
            break
        }
        case 'signals_scout': {
            const file = signal.source_id.match(REPO_FILE_ID)?.[2]
            parts.push(file ? (file.split('/').pop() ?? null) : null)
            break
        }
    }
    return parts.filter((part): part is string => !!part)
}

export function signalMeta(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'extra'>
): string {
    return signalMetaParts(signal).join(' · ')
}

function recordingOffsetSeconds(extra: Record<string, unknown>): number | null {
    if (typeof extra.start_time === 'number' && Number.isFinite(extra.start_time)) {
        return extra.start_time
    }
    if (typeof extra.start_time === 'string') {
        return reverseColonDelimitedDuration(extra.start_time)
    }
    return null
}

function recordingStart(extra: Record<string, unknown>): string | null {
    const value = extra.recording_start_time ?? extra.session_start_time
    return typeof value === 'string' ? value : null
}

export function signalDestination(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'content' | 'extra'>
): TodaySignalDestination {
    const extra = extraOf(signal)
    if (
        (signal.source_product === 'replay_vision' || signal.source_product === 'session_replay') &&
        typeof extra.session_id === 'string' &&
        extra.session_id
    ) {
        const offset = recordingOffsetSeconds(extra)
        const start = recordingStart(extra)
        return {
            kind: 'recording',
            sessionId: extra.session_id,
            timestamp: offset !== null && start ? dayjs(start).add(offset, 'second').valueOf() : null,
            offset: offset !== null ? colonDelimitedDuration(offset, 2) : null,
        }
    }
    if (signal.source_product === 'error_tracking' && signal.source_id) {
        const fingerprint = typeof extra.fingerprint === 'string' ? extra.fingerprint : undefined
        return {
            kind: 'link',
            to: urls.errorTrackingIssue(signal.source_id, fingerprint ? { fingerprint } : {}),
            external: false,
            label: 'Open issue',
        }
    }
    if (signal.source_product === 'conversations') {
        const to = conversationsTicketUrl({ source_id: signal.source_id, extra: signal.extra })
        if (to) {
            return { kind: 'link', to, external: false, label: 'Open ticket' }
        }
    }
    if (signal.source_product === 'analytics') {
        const notebook = stringField(extra, 'notebook_short_id')
        if (notebook) {
            return { kind: 'link', to: urls.notebook(notebook), external: false, label: 'Open investigation' }
        }
        const insight = stringField(extra, 'insight_short_id')
        if (insight) {
            return { kind: 'link', to: urls.insightView(insight as never), external: false, label: 'Open insight' }
        }
    }
    if (signal.source_product === 'github') {
        const to = safeHttpUrl(stringField(extra, 'html_url') ?? '')
        if (to) {
            return {
                kind: 'link',
                to,
                external: true,
                label: isPullRequest(signal) ? 'Open pull request' : 'Open issue',
            }
        }
    }
    if (signal.source_product === 'signals_scout') {
        const to = signalSlackThread(signal)
        if (to) {
            return { kind: 'link', to, external: true, label: 'Open thread' }
        }
        const file = signal.source_id.match(REPO_FILE_ID)
        if (file && signal.content.length <= 240) {
            return {
                kind: 'link',
                to: `https://github.com/${file[1]}/blob/master/${file[2]}`,
                external: true,
                label: 'Open file',
            }
        }
    }
    const link = genericSignalLink({ source_product: signal.source_product, source_id: signal.source_id, extra })
    return link ? { kind: 'link', to: link.to, external: link.external, label: 'Open' } : { kind: 'read' }
}

const PROPOSAL_CHARS = 260

/** The proposal the page shows: the report's fix, or the prompt it suggests, cut to a short read. */
export function reportProposal(report: SignalReport, sections: Pick<TodayReportSections, 'proposal'>): string {
    return conciseText(
        sections.proposal ?? (isActionCapableReport(report) ? report.suggested_prompts?.[0] : null),
        PROPOSAL_CHARS
    )
}

const IMPACT_CHARS = 180

/** The impact paragraph's opening, when it states a measurement in plain words. */
export function impactSentence(sections: Pick<TodayReportSections, 'impact'>): string {
    const text = conciseText(sections.impact, IMPACT_CHARS)
    return text && /\d/.test(text) && !mentionsCodePath(text) ? text : ''
}

/** The Slack thread a scout's finding cites, when it cites one. */
export function signalSlackThread(signal: Pick<SignalNodeApi, 'source_product' | 'content'>): string | null {
    const thread = signal.source_product === 'signals_scout' ? signal.content.match(SLACK_LINK)?.[0] : null
    return thread ? safeHttpUrl(thread.replace(/[).,]+$/, '')) : null
}

export interface TodayCodeFile {
    repo: string
    path: string
}

/** The repository file a scout's finding is about, when its source id names one. */
export function signalCodeFile(signal: Pick<SignalNodeApi, 'source_product' | 'source_id'>): TodayCodeFile | null {
    const file = signal.source_product === 'signals_scout' ? signal.source_id.match(REPO_FILE_ID) : null
    return file ? { repo: file[1], path: file[2] } : null
}

const CODE_SPAN = /`([^`\n]{3,80})`/g

/** The code a finding quotes in backticks, leaving out file names. */
export function codeIdentifiers(content: string): string[] {
    const spans = [...content.matchAll(CODE_SPAN)].map((match) => match[1].trim())
    return [...new Set(spans.filter((span) => !/\//.test(span) && !/^[\w-]+\.[a-z]{1,5}$/i.test(span)))]
}

export interface TodayCodeExcerpt {
    /** The 1-based number of the first line shown. */
    startLine: number
    lines: string[]
    marks: { line: number; start: number; end: number }[]
}

const EXCERPT_CONTEXT_LINES = 2
const EXCERPT_WINDOW_LINES = 5
const MAX_EXCERPT_CANDIDATES = 5
const CANDIDATE_SLACK = 2
const IMPORT_LINE = /^\s*(import\b|from\s+\S+\s+import\b|export\s+\{.*\}\s+from\b)/

interface ScoredAnchor {
    anchor: number
    found: number
    score: number
}

function scoredAnchors(fileLines: string[], content: string, identifiers: string[]): ScoredAnchor[] {
    // A rare identifier names the exact place a finding means, so it weighs more than a common one.
    const weight = new Map(
        identifiers.map((identifier) => [identifier, 1 / Math.max(1, content.split(identifier).length - 1)])
    )
    const anchors: ScoredAnchor[] = []
    fileLines.forEach((line, index) => {
        if (IMPORT_LINE.test(line) || !identifiers.some((identifier) => line.includes(identifier))) {
            return
        }
        const window = fileLines
            .slice(Math.max(0, index - EXCERPT_CONTEXT_LINES), index + EXCERPT_WINDOW_LINES + 1)
            .join('\n')
        const found = identifiers.filter((identifier) => window.includes(identifier))
        const rarity = found.reduce((total, identifier) => total + (weight.get(identifier) ?? 0), 0)
        anchors.push({ anchor: index, found: found.length, score: found.length + rarity / (identifiers.length + 1) })
    })
    return anchors.sort((first, second) => second.score - first.score || first.anchor - second.anchor)
}

function excerptAt(fileLines: string[], identifiers: string[], anchor: number): TodayCodeExcerpt {
    let start = Math.max(0, anchor - EXCERPT_CONTEXT_LINES)
    let end = Math.min(fileLines.length - 1, anchor + EXCERPT_WINDOW_LINES)
    while (start < anchor && !fileLines[start].trim()) {
        start++
    }
    while (end > anchor && !fileLines[end].trim()) {
        end--
    }
    const window = fileLines.slice(start, end + 1)
    const indent = Math.min(
        ...window.filter((line) => line.trim()).map((line) => line.length - line.trimStart().length)
    )
    const lines = window.map((line) => line.slice(indent))
    const marks = lines.flatMap((line, index) =>
        identifiers.flatMap((identifier) => {
            const found: { line: number; start: number; end: number }[] = []
            let at = line.indexOf(identifier)
            while (at >= 0) {
                found.push({ line: index, start: at, end: at + identifier.length })
                at = line.indexOf(identifier, at + identifier.length)
            }
            return found
        })
    )
    return { startLine: start + 1, lines, marks }
}

/**
 * The places in a file that could show what a finding quotes, best first: windows that hold all or nearly all
 * of the quoted pieces, and never overlap.
 */
export function codeExcerptCandidates(
    content: string,
    identifiers: string[],
    limit: number = MAX_EXCERPT_CANDIDATES
): TodayCodeExcerpt[] {
    if (!identifiers.length) {
        return []
    }
    const fileLines = content.split('\n')
    const anchors = scoredAnchors(fileLines, content, identifiers)
    const mostFound = anchors[0]?.found ?? 0
    const excerpts: TodayCodeExcerpt[] = []
    for (const { anchor, found } of anchors) {
        if (excerpts.length >= limit || found < Math.max(1, mostFound - CANDIDATE_SLACK)) {
            break
        }
        const excerpt = excerptAt(fileLines, identifiers, anchor)
        const last = excerpt.startLine + excerpt.lines.length - 1
        const overlaps = excerpts.some(
            (taken) => excerpt.startLine <= taken.startLine + taken.lines.length - 1 && last >= taken.startLine
        )
        if (!overlaps) {
            excerpts.push(excerpt)
        }
    }
    return excerpts
}

/** The lines of a file around the place a finding talks about, with the quoted code marked. */
export function codeExcerpt(content: string, identifiers: string[]): TodayCodeExcerpt | null {
    return codeExcerptCandidates(content, identifiers, 1)[0] ?? null
}

export type TodayOccurrenceKind = 'sessions' | 'tickets' | 'alerts'

export interface TodayOccurrences {
    kind: TodayOccurrenceKind
    count: number
    people: number | null
    oldest: string
    newest: string
    buckets: number[]
    bucketDays: number
    windowDays: number
}

export type TodayInlineSegment =
    | { kind: 'text' | 'strong' | 'code'; text: string }
    | { kind: 'link'; text: string; href: string }

const INLINE_MARKDOWN = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g

export function inlineSegments(markdown: string): TodayInlineSegment[] {
    const text = readableDates(shortenGitHubLinks(markdown).replace(/\s+/g, ' ').trim())
    const segments: TodayInlineSegment[] = []
    let last = 0
    for (const match of text.matchAll(INLINE_MARKDOWN)) {
        const index = match.index ?? 0
        if (index > last) {
            segments.push({ kind: 'text', text: text.slice(last, index) })
        }
        if (match[1] !== undefined) {
            segments.push({ kind: 'code', text: match[1] })
        } else if (match[2] !== undefined) {
            segments.push(
                ...inlineSegments(match[2]).map((segment) =>
                    segment.kind === 'text' ? { ...segment, kind: 'strong' as const } : segment
                )
            )
        } else {
            segments.push({ kind: 'link', text: match[3], href: match[4] })
        }
        last = index + match[0].length
    }
    if (last < text.length) {
        segments.push({ kind: 'text', text: text.slice(last) })
    }
    return segments
}

export interface TodayFigure {
    start: number
    end: number
    text: string
    value: string
    noun: string | null
}

const FIGURE =
    /(?<![\w.,\-/:#$@→])(?:[$€£])?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s?[–-]\s?(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?))?(?:%|\s?(?:ms|K|M)\b)?(?![\w:/→]|[.,]\d)/g
const YEAR = /^(19|20)\d{2}$/
const MONTH_AFTER = /^\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/
const TIME_UNIT = /^(?:hours?|days?|weeks?|months?|years?)$/i
// A duration reads as one quantity, so its unit is part of the mark: "26 seconds", "17 minutes".
const DURATION_UNIT = /^(?:seconds?|minutes?|hours?|days?|weeks?|months?)$/i
const WINDOW_LEAD = /\b(?:trailing|last|past|previous|next|over|within|in)(?:\s+the)?\s+$/i
const UNIT = /(%|ms|K|M)$/
const CURRENCY = /^[$€£]/

/**
 * Counts and amounts in a sentence. A time window like "the trailing 14 days" frames a claim, so it is not one,
 * and neither is a bare number with no word after it, which is usually a status code or an identifier.
 */
export function findFigures(text: string): TodayFigure[] {
    return numbersIn(text)
        .filter((figure) => figure.noun || UNIT.test(figure.text) || CURRENCY.test(figure.text))
        .filter(
            (figure) => !(figure.noun && TIME_UNIT.test(figure.noun) && WINDOW_LEAD.test(text.slice(0, figure.start)))
        )
}

function numbersIn(text: string): TodayFigure[] {
    return [...text.matchAll(FIGURE)]
        .filter((match) => !YEAR.test(match[1]) && !/^0\d/.test(match[1]))
        .filter((match) => !MONTH_AFTER.test(text.slice((match.index ?? 0) + match[0].length)))
        .map((match) => {
            const start = match.index ?? 0
            const numberEnd = start + match[0].length
            const noun = text.slice(numberEnd).match(/^\s+['"‘“]?([A-Za-z][A-Za-z-]*)/)?.[1] ?? null
            const unit = noun && DURATION_UNIT.test(noun) ? text.slice(numberEnd).match(/^\s+[A-Za-z]+/)?.[0] : null
            const end = numberEnd + (unit?.length ?? 0)
            return { start, end, text: text.slice(start, end), value: match[1], noun }
        })
}

const AUDIENCE_NOUN =
    /^(?:people|persons?|users?|teams?|customers?|organi[sz]ations?|orgs?|accounts?|companies|company|projects?|workspaces?|sessions?|visitors?|members?)$/i

/** Picks the figures worth marking: counts of people and teams first, then the rest, each in reading order. */
export function figuresToMark<T extends Pick<TodayFigure, 'noun'>>(figures: T[], limit: number): Set<T> {
    const ranked = figures
        .map((figure, index) => ({ figure, index, audience: figure.noun && AUDIENCE_NOUN.test(figure.noun) ? 0 : 1 }))
        .sort((first, second) => first.audience - second.audience || first.index - second.index)
    return new Set(ranked.slice(0, limit).map(({ figure }) => figure))
}

/** The amount a figure stands for, with its K or M multiplier applied. */
function figureAmount(figure: Pick<TodayFigure, 'text' | 'value'>): number {
    const scale = figure.text.endsWith('K') ? 1000 : figure.text.endsWith('M') ? 1000000 : 1
    return Number(figure.value.replace(/,/g, '')) * scale
}

export interface TodayResearchNote {
    text: string
    at: string
    signalId: string | null
}

const RESEARCH_FIELDS: Record<string, string> = {
    priority_judgment: 'explanation',
    actionability_judgment: 'explanation',
    signal_finding: 'data_queried',
    check_scheduled: 'rationale',
    note: 'note',
}

// A verification plan says what a later check should find, so its numbers are expectations rather than evidence.
const PLAN_NOTE = /^#+\s*verification plan/i

function textField(content: unknown, key: string): string | null {
    const value =
        content && typeof content === 'object' && !Array.isArray(content)
            ? (content as Record<string, unknown>)[key]
            : null
    return typeof value === 'string' && value.trim() ? value : null
}

/** The agent's current research: the newest judgment of each kind, the newest finding per signal, and every check. */
export function researchNotes(
    artefacts:
        | readonly { type: string; content: unknown; created_at: string; created_by?: unknown }[]
        | null
        | undefined
): TodayResearchNote[] {
    const seen = new Set<string>()
    const notes: TodayResearchNote[] = []
    const newestFirst = [...(artefacts ?? [])].sort((first, second) =>
        second.created_at.localeCompare(first.created_at)
    )
    for (const artefact of newestFirst) {
        const field = RESEARCH_FIELDS[artefact.type]
        const text = field ? textField(artefact.content, field) : null
        const signalId = artefact.type === 'signal_finding' ? textField(artefact.content, 'signal_id') : null
        const key = ['check_scheduled', 'note'].includes(artefact.type) ? null : `${artefact.type}:${signalId ?? ''}`
        if (!text || artefact.created_by || PLAN_NOTE.test(text) || (key && seen.has(key))) {
            continue
        }
        if (key) {
            seen.add(key)
        }
        notes.push({ text, at: artefact.created_at, signalId })
    }
    return notes
}

function withoutDigitCommas(text: string): string {
    return text.replace(/(\d),(?=\d{3}\b)/g, '$1')
}

function proseSentences(markdown: string): string[] {
    return markdown
        .replace(/```[\s\S]*?(```|$)/g, '\n')
        .split('\n')
        .map(plainLine)
        .filter(Boolean)
        .flatMap((line) => line.split(SENTENCE_BREAK))
        .map((sentence) => sentence.trim())
        .filter(Boolean)
}

const COMMON_WORDS = new Set(
    'about across after again also because been before being between both could does doing during each every from have into just more most much only other over same since some still such than that their them then there these they this those through under until very were what when where which while with would your'.split(
        ' '
    )
)

function wordStems(text: string): Set<string> {
    return new Set(
        (text.toLowerCase().match(/[a-z][a-z'-]{3,}/g) ?? [])
            .filter((word) => !COMMON_WORDS.has(word))
            .map((word) => word.slice(0, 5))
    )
}

function overlap(first: Set<string>, second: Set<string>): number {
    let shared = 0
    for (const stem of first) {
        shared += second.has(stem) ? 1 : 0
    }
    return shared
}

function numberBody(value: string): string {
    const [whole, fraction] = withoutDigitCommas(value).split('.')
    return whole.split('').join(',?') + (fraction ? `\\.${fraction}` : '')
}

function numberPattern(value: string): RegExp {
    return new RegExp(`(?<![\\d.,/:-])${numberBody(value)}(?![\\d/:-]|[.,]\\d)`)
}

/**
 * Splits text so the numbers in `values` can be emphasized, in the order given and once each,
 * whether or not they are written with commas. A day of the month is never one of them.
 */
export function highlightSegments(text: string, values: string[]): { text: string; marked: boolean }[] {
    const segments: { text: string; marked: boolean }[] = []
    let last = 0
    for (const value of values) {
        const pattern = new RegExp(
            `(?:[$€£])?${numberPattern(value).source}(?:\\s?(?:ms|K|M)\\b|%|\\s(?:seconds?|minutes?|hours?)\\b)?`,
            'g'
        )
        pattern.lastIndex = last
        let match = pattern.exec(text)
        while (match && MONTH_AFTER.test(text.slice(match.index + match[0].length))) {
            match = pattern.exec(text)
        }
        if (!match) {
            continue
        }
        if (match.index > last) {
            segments.push({ text: text.slice(last, match.index), marked: false })
        }
        segments.push({ text: match[0], marked: true })
        last = match.index + match[0].length
    }
    if (last < text.length) {
        segments.push({ text: text.slice(last), marked: false })
    }
    return segments
}

const EXCERPT_BEFORE = 120
const EXCERPT_AFTER = 160

const CLAUSE_END = /\)?[,;]\s|\s[—–]\s/g
const CLAUSE_START = /[,;:]\s|\s[—–]\s/g
const EXCERPT_REACH = 130
const CLAUSE_MIN_TAIL = 4

function excerptStart(sentence: string, first: number): number {
    if (first <= EXCERPT_REACH) {
        return 0
    }
    for (const match of sentence.slice(0, first).matchAll(CLAUSE_START)) {
        const index = (match.index ?? 0) + match[0].length
        if (first - index <= EXCERPT_REACH) {
            return index
        }
    }
    return sentence.indexOf(' ', first - EXCERPT_BEFORE) + 1
}

/** The part of a long sentence around the emphasized numbers, cut at the clause after the last one. */
export function excerptAround(sentence: string, needles: string[]): string {
    const positions = needles
        .map((needle) => {
            const match = numberPattern(needle).exec(sentence)
            return match ? { start: match.index, end: match.index + match[0].length } : null
        })
        .filter((position): position is { start: number; end: number } => position !== null)
    if (!positions.length || sentence.length <= EXCERPT_BEFORE + EXCERPT_AFTER) {
        return sentence
    }
    const first = Math.min(...positions.map((position) => position.start))
    const last = Math.max(...positions.map((position) => position.end))
    const start = excerptStart(sentence, first)
    CLAUSE_END.lastIndex = last + CLAUSE_MIN_TAIL
    const clause = CLAUSE_END.exec(sentence)
    const limit = Math.min(sentence.length, last + EXCERPT_AFTER)
    const wordEnd = limit === sentence.length ? limit : sentence.lastIndexOf(' ', limit)
    const end = clause && clause.index < limit ? clause.index + (clause[0].startsWith(')') ? 1 : 0) : wordEnd
    const body = sentence.slice(start, end).replace(/[\s,;:–—-]+$/, '')
    return `${start > 0 ? '…' : ''}${body}${end < sentence.length && !/[.!?]$/.test(body) ? '…' : ''}`
}

type TodaySourceText = { text: string; signal: SignalNodeApi | null; note: TodayResearchNote | null }

interface TodayFigureMatch {
    score: number
    source: TodaySourceText
    sentence: string
    shownValues: string[]
    parts: string[] | null
    exact?: string | null
}

export interface TodayFigureContext {
    signals: SignalNodeApi[]
    research: TodayResearchNote[]
    summary: string | null | undefined
    shownText: string
}

interface TodayFigureExcerpt {
    excerpt: string
    /** The numbers in the excerpt that back the figure: the figure itself, a rounded form of it, or its parts. */
    values: string[]
    /** Set when the figure is a total of numbers the source gives separately. */
    parts: string[] | null
    /** Set when the figure rounds a more exact number in the source. */
    exact?: string | null
}

export type TodayFigureSource =
    | ({ kind: 'signal'; signal: SignalNodeApi } & TodayFigureExcerpt)
    | ({ kind: 'research'; note: TodayResearchNote; signal: SignalNodeApi | null } & TodayFigureExcerpt)
    | ({ kind: 'report' } & TodayFigureExcerpt)

const MIN_SUM = 10
const MIN_SUM_OVERLAP = 2
const MIN_CONTEXT_OVERLAP = 3

function addsUpTo(sentence: string, target: number): string[] | null {
    const values = numbersIn(sentence)
        .filter((figure) => !figure.text.includes('%') && !/[–-]/.test(figure.text))
        .map((figure) => figure.value)
    for (let size = 2; size <= 3; size++) {
        for (let index = 0; index + size <= values.length; index++) {
            const parts = values.slice(index, index + size)
            const sum = parts.reduce((total, part) => total + Number(withoutDigitCommas(part)), 0)
            if (sum === target) {
                return parts
            }
        }
    }
    return null
}

// Agents start sentences with lowercase product names ("pganalyze rates it…"). A word of three or more letters
// before the stop keeps abbreviations like "e.g." together.
const LOWERCASE_SENTENCE_BREAK = /(?<=\b[a-z]{3,}[.!?])\s+(?=[a-z])/

const FUNCTION_WORDS = new Set(
    'a across after against an and as at before by for from in into of on or out over per than the to under with'.split(
        ' '
    )
)
const APPROXIMATE_LEAD = /\b(?:about|around|roughly|nearly|almost|approximately|over|under|~)\s*$/i
const APPROXIMATE_TOLERANCE = 0.06

function closeTo(sentence: string, target: number): string | null {
    for (const candidate of numbersIn(sentence)) {
        const amount = figureAmount(candidate)
        if (amount > 0 && Math.abs(amount - target) / target <= APPROXIMATE_TOLERANCE) {
            return candidate.value
        }
    }
    return null
}

/** Where a figure on the page comes from: a signal that states it, the agent's research, or the rest of the report. */
export function figureSource(
    figure: Pick<TodayFigure, 'text' | 'value' | 'noun'>,
    { signals, research, summary, shownText }: TodayFigureContext
): TodayFigureSource | null {
    const amount = figureAmount(figure)
    const unit = figure.text.match(UNIT)?.[1] ?? null
    const pattern = new RegExp(
        `${numberPattern(figure.value).source}${unit && unit !== 'K' && unit !== 'M' ? `\\s?${unit}` : ''}`
    )
    const noun = figure.noun && !FUNCTION_WORDS.has(figure.noun.toLowerCase()) ? figure.noun : null
    const stem = noun && noun.length > 2 ? noun.slice(0, 4).toLowerCase() : null
    const needsNoun = amount < 100 && !unit
    const claim = proseSentences(shownText).find((sentence) => sentence.includes(figure.text)) ?? plainLine(shownText)
    const claimStems = wordStems(claim)
    const approximate =
        unit === 'K' || unit === 'M' || APPROXIMATE_LEAD.test(claim.slice(0, Math.max(0, claim.indexOf(figure.text))))
    const shown = withoutDigitCommas(plainLine(shownText))
    const signalById = new Map(signals.map((signal) => [signal.signal_id, signal]))

    const texts: (TodaySourceText & { weight: number })[] = [
        ...signals.map((signal) => ({ text: signal.content, signal, note: null, weight: 1 })),
        ...research.map((note) => ({
            text: note.text,
            signal: note.signalId ? (signalById.get(note.signalId) ?? null) : null,
            note,
            weight: 0.5,
        })),
        { text: summary ?? '', signal: null, note: null, weight: 0 },
    ]

    let best: TodayFigureMatch | null = null
    let bestScore = 0
    for (const source of texts) {
        for (const sentence of proseSentences(source.text).flatMap((line) => line.split(LOWERCASE_SENTENCE_BREAK))) {
            if (!source.note && !source.signal && shown.includes(withoutDigitCommas(sentence))) {
                continue
            }
            const shared = Math.min(overlap(claimStems, wordStems(sentence)), 5)
            const nounScore = stem && sentence.toLowerCase().includes(stem) ? 2 : 0
            const base = { source, sentence }
            let match: TodayFigureMatch | null = null
            if (pattern.test(sentence)) {
                if (!needsNoun || nounScore || shared >= (stem ? MIN_CONTEXT_OVERLAP : MIN_SUM_OVERLAP)) {
                    const score = 10 + nounScore + shared * 0.5 + source.weight
                    match = { ...base, score, shownValues: [figure.value], parts: null }
                }
            } else if (shared >= MIN_SUM_OVERLAP) {
                const near = approximate ? closeTo(sentence, amount) : null
                const parts: string[] | null =
                    !near && amount >= MIN_SUM && bestScore < 10 ? addsUpTo(sentence, amount) : null
                if (near) {
                    const score = 10 + nounScore + shared * 0.5 + source.weight
                    const exact = Number(near.replace(/,/g, '')).toLocaleString('en-US')
                    match = { ...base, score, shownValues: [near], parts: null, exact }
                } else if (parts) {
                    match = { ...base, score: shared * 0.5 + source.weight, shownValues: parts, parts }
                }
            }
            if (match && match.score > bestScore) {
                best = match
                bestScore = match.score
            }
        }
    }
    const found = best
    if (!found) {
        return null
    }
    const excerpt = readableExcerpt(excerptAround(found.sentence, found.shownValues))
    const { note, signal } = found.source
    const shared = { excerpt, values: found.shownValues, parts: found.parts, exact: found.exact ?? null }
    if (note) {
        return { kind: 'research', note, signal, ...shared }
    }
    if (signal) {
        return { kind: 'signal', signal, ...shared }
    }
    return { kind: 'report', ...shared }
}

export type TodayFigureCardContent =
    | ({
          kind: 'signal'
          signal: SignalNodeApi
          /** How a computed figure follows from the numbers in the quote. */
          working?: { expression: string; result: string }
      } & Partial<TodayFigureExcerpt> & { excerpt: string })
    | ({ kind: 'research'; note: TodayResearchNote; signal: SignalNodeApi | null } & TodayFigureExcerpt)
    | ({ kind: 'report' } & TodayFigureExcerpt)
    | {
          kind: 'metric'
          total: string
          /** When the saved query last measured the figure. */
          at: string | null
          /** The first and last day of the chart. */
          range: { from: string; to: string } | null
          caption: string | null
          window: string | null
          trend: number[] | null
          link: { url: string; label: string } | null
      }
    | { kind: 'none' }

export function figureCardContent(
    figure: Pick<TodayFigure, 'text' | 'value' | 'noun'>,
    context: TodayFigureContext
): TodayFigureCardContent {
    return figureSource(figure, context) ?? { kind: 'none' }
}

export interface TodayMarkedFigure extends TodayFigure {
    segment: number
    content: TodayFigureCardContent
}

const MAX_MARKS = 4

/** The figures to mark in a piece of prose: only ones with a source, at most three, counts of people first. */
export function markedFigures(
    markdown: string,
    resolve: (figure: TodayFigure) => TodayFigureCardContent
): TodayMarkedFigure[] {
    const sourced = inlineSegments(markdown).flatMap((segment, index) =>
        segment.kind === 'text' || segment.kind === 'strong'
            ? findFigures(segment.text)
                  .map((figure) => ({ ...figure, segment: index, content: resolve(figure) }))
                  .filter((figure) => figure.content.kind !== 'none')
            : []
    )
    const chosen = figuresToMark(sourced, MAX_MARKS)
    return sourced.filter((figure) => chosen.has(figure))
}

export const STALE_AFTER_DAYS = 7

/** Whole calendar days between a date and today. */
export function daysAgo(date: string, now: Dayjs = dayjs()): number {
    return now.startOf('day').diff(dayjs(date).startOf('day'), 'day')
}

function sourceDate(content: TodayFigureCardContent): string | null {
    return content.kind === 'research' ? content.note.at : content.kind === 'signal' ? content.signal.timestamp : null
}

/** The date of the newest evidence behind marked figures, when even that is more than a week old. */
export function staleEvidenceDate(figures: TodayMarkedFigure[], now: Dayjs = dayjs()): string | null {
    const newest = figures
        .map((figure) => sourceDate(figure.content))
        .filter((date): date is string => date !== null)
        .sort()
        .at(-1)
    return newest && daysAgo(newest, now) > STALE_AFTER_DAYS ? newest : null
}

/** An old quote that says "today" means the day it was written, so the quote names that day. */
export function anchorToday(text: string, date: string, now: Dayjs = dayjs()): string {
    return daysAgo(date, now) > 0
        ? text.replace(/\btoday\b/gi, (word) => `${word} [${dayjs(date).format('D MMM')}]`)
        : text
}

export type TodayWorkKind = 'implement' | 'investigate'

export function reportWorkKind(report: Pick<SignalReport, 'actionability' | 'status'>): TodayWorkKind {
    return report.actionability === 'immediately_actionable' && report.status !== 'pending_input'
        ? 'implement'
        : 'investigate'
}

export function buildReportInvestigationPrompt(report: Pick<SignalReport, 'id'>, reportUrl: string): string {
    return `Investigate the PostHog Inbox report at ${reportUrl} (report ID: ${report.id}).

Use the PostHog MCP tools to read the report and its full work log with inbox-report-artefacts-list. Confirm the problem it describes against the current code and data, and find the root cause.

Reply with what you found: whether the problem is real, what causes it, how many people it affects, and the smallest fix you would make. Do not change code, open a pull request, or change the report's state.`
}

const PGANALYZE_TIME = /takes ([\d.,]+)\s*ms on average/i
const PGANALYZE_CALLS = /([\d,]+) calls in last 24h/i

export interface TodayQueryCost {
    averageMs: string
    callsPerDay: string
    hoursPerDay: string | null
    exactHoursPerDay: string | null
}

export function pganalyzeQueryCost(signals: SignalNodeApi[]): TodayQueryCost | null {
    for (const signal of signals) {
        if (signal.source_product !== 'pganalyze') {
            continue
        }
        const time = signal.content.match(PGANALYZE_TIME)?.[1]
        const calls = signal.content.match(PGANALYZE_CALLS)?.[1]
        if (time && calls) {
            const count = Number(calls.replace(/,/g, ''))
            const hours = (Number(time.replace(/,/g, '')) * count) / 3_600_000
            return {
                averageMs: time,
                callsPerDay: Number.isFinite(count) ? humanFriendlyNumber(count, 0) : calls,
                hoursPerDay:
                    Number.isFinite(hours) && hours > 0 ? humanFriendlyNumber(hours, hours < 10 ? 1 : 0) : null,
                exactHoursPerDay: Number.isFinite(hours) && hours > 0 ? hours.toFixed(2) : null,
            }
        }
    }
    return null
}

const DAY_MS = 24 * 60 * 60 * 1000
const MIN_WINDOW_DAYS = 14
const MAX_WINDOW_DAYS = 91
const DAILY_UP_TO_DAYS = 31

function occurrenceKey(
    signal: SignalNodeApi
): { kind: TodayOccurrenceKind; key: string; person: string | null } | null {
    const extra = extraOf(signal)
    if (signal.source_product === 'replay_vision' || signal.source_product === 'session_replay') {
        const session = stringField(extra, 'session_id')
        return session ? { kind: 'sessions', key: session, person: stringField(extra, 'distinct_id') } : null
    }
    if (signal.source_product === 'conversations' || signal.source_product === 'zendesk') {
        const ticket = typeof extra.ticket_number === 'number' ? String(extra.ticket_number) : signal.source_id
        return ticket ? { kind: 'tickets', key: ticket, person: null } : null
    }
    if (signal.source_product === 'analytics' && signal.source_type === 'anomaly_investigation') {
        const check = stringField(extra, 'alert_check_id') ?? signal.source_id
        return check ? { kind: 'alerts', key: check, person: null } : null
    }
    return null
}

/** When the problem last happened: the newest recording, ticket or alert behind the report. */
export function lastOccurrence(signals: SignalNodeApi[]): string | null {
    const newest = reportOccurrences(signals)
        .map((occurrences) => occurrences.newest)
        .sort()
        .pop()
    return newest ?? null
}

export function reportOccurrences(signals: SignalNodeApi[], now: number = Date.now()): TodayOccurrences[] {
    const byKind = new Map<TodayOccurrenceKind, Map<string, { time: number; person: string | null }>>()
    for (const signal of signals) {
        const occurrence = occurrenceKey(signal)
        const time = new Date(signal.timestamp).getTime()
        if (!occurrence || !Number.isFinite(time)) {
            continue
        }
        const seen = byKind.get(occurrence.kind) ?? new Map()
        const previous = seen.get(occurrence.key)
        if (!previous || time < previous.time) {
            seen.set(occurrence.key, { time, person: occurrence.person })
        }
        byKind.set(occurrence.kind, seen)
    }
    return [...byKind.entries()]
        .map(([kind, seen]) => {
            const items = [...seen.values()]
            const times = items.map((item) => item.time)
            const oldest = Math.min(...times)
            const windowDays = Math.min(
                MAX_WINDOW_DAYS,
                Math.max(MIN_WINDOW_DAYS, Math.ceil((now - oldest) / DAY_MS) + 1)
            )
            const bucketDays = windowDays <= DAILY_UP_TO_DAYS ? 1 : 7
            const bucketCount = Math.ceil(windowDays / bucketDays)
            const buckets = Array.from({ length: bucketCount }, () => 0)
            for (const time of times) {
                const age = Math.floor((now - time) / (bucketDays * DAY_MS))
                if (age >= 0 && age < bucketCount) {
                    buckets[bucketCount - 1 - age] += 1
                }
            }
            const people = new Set(items.map((item) => item.person).filter(Boolean))
            return {
                kind,
                count: items.length,
                people: kind === 'sessions' && people.size > 0 ? people.size : null,
                oldest: new Date(oldest).toISOString(),
                newest: new Date(Math.max(...times)).toISOString(),
                buckets,
                bucketDays,
                windowDays: bucketCount * bucketDays,
            }
        })
        .sort((first, second) => second.count - first.count)
}
