import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { Dayjs } from 'lib/dayjs'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { type InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import type { TeamPublicType, TeamType } from '~/types'

import type { HighlightFeedItemApi } from 'products/replay_vision/frontend/generated/api.schemas'
import { highlightPickSummary } from 'products/replay_vision/frontend/replay_scanners/highlightPickSummary'
import type { ReportChartApi, SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'
import { prettifyScoutSkillName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

export const FEED_DAYS = 14
export const FEED_MAX_POSTS = 15
/** Every post reads as a short summary, so no text runs past this many characters. */
export const FEED_TEXT_LIMIT = 200
const WEEK = 7
const MIN_WEEKLY_VOLUME = 200
const MIN_CHANGE = 0.3
const MIN_RAGE_CLICKS = 3
const MAX_SCOUT_POSTS = 8
const MAX_MOVEMENTS = 2
const MAX_REPLAYS = 2
const MAX_FEATURE_POSTS = 2
// Paired events, such as a start and a finish, move by the same ratio and would tell one story twice.
const SAME_STORY_RATIO = 0.15

// Plumbing events move with SDK changes, not with how people use the product.
const BUILT_IN_EVENTS_WORTH_A_STORY = new Set(['$pageview', '$screen', '$rageclick'])

/**
 * Scouts that watch product data, and the product each one posts as. Other scouts write engineering work
 * (fixes, CI, repo digests), which is not news. The feed asks the API for these names only, because on a busy
 * project engineering reports fill every page.
 */
const DATA_SCOUT_PRODUCTS: Record<string, string> = {
    'signals-scout-anomaly-detection': 'product_analytics',
    'signals-scout-product-analytics': 'product_analytics',
    'signals-scout-customer-analytics': 'product_analytics',
    'signals-scout-customer-analytics-billing-and-usage': 'product_analytics',
    'signals-scout-insight-alerts': 'alerts',
    'signals-scout-web-analytics': 'web_analytics',
    'signals-scout-web-vitals': 'web_analytics',
    'signals-scout-session-replay': 'session_replay',
    'signals-scout-replay-vision': 'session_replay',
    'signals-scout-experiments': 'experiments',
    'signals-scout-feature-flags': 'feature_flags',
    'signals-scout-surveys': 'surveys',
    'signals-scout-revenue-analytics': 'revenue_analytics',
    'signals-scout-ai-observability': 'ai_observability',
}

export const DATA_SCOUT_NAMES = Object.keys(DATA_SCOUT_PRODUCTS)

export type TodayFeedKind = 'scout' | 'movement' | 'replay' | 'feature' | 'preview'

export interface TodayFeedAuthor {
    name: string
    handle: string
    product?: string
}

export type TodayFeedMedia =
    | { type: 'chart'; label: string; current: number; previous: number; series: number[]; days: string[] }
    | { type: 'report-chart'; chart: ReportChartApi }
    | { type: 'replay'; sessionId: string; page: string | null; caption: string }
    | { type: 'card'; title: string; description: string; actionLabel: string; enrollFlagKey?: string }

export interface TodayFeedPost {
    key: string
    kind: TodayFeedKind
    author: TodayFeedAuthor
    at: string | null
    text: string
    to: string
    product?: string
    media: TodayFeedMedia | null
}

export interface DayCount {
    name: string
    daysAgo: number
    count: number
}

export interface RageSession {
    sessionId: string
    clicks: number
    url: string | null
    startedAt: string | null
}

export interface FeedPreviewFeature {
    flagKey: string
    name: string
    description: string
    stage: string
    enabled: boolean
}

export type FeedScoutReport = Pick<
    SignalReportListApi,
    'id' | 'title' | 'summary' | 'summary_lead' | 'scout_name' | 'created_at' | 'charts'
>

export interface TodayFeedInputs {
    team: TeamPublicType | TeamType | null
    today: Dayjs
    scoutReports: FeedScoutReport[]
    eventCounts: DayCount[]
    replayPicks: HighlightFeedItemApi[]
    rageSession: RageSession | null
    previews: FeedPreviewFeature[]
    hiddenKeys: Record<string, true>
}

const PRODUCT_ANALYTICS: TodayFeedAuthor = {
    name: 'Product analytics',
    handle: '@product_analytics',
    product: 'product_analytics',
}
const SESSION_REPLAY: TodayFeedAuthor = { name: 'Session replay', handle: '@session_replay', product: 'session_replay' }
const POSTHOG: TodayFeedAuthor = { name: 'PostHog', handle: '@posthog' }

/** Cuts text to the feed's limit on a word boundary. */
export function shortText(text: string, limit: number = FEED_TEXT_LIMIT): string {
    const clean = text.replace(/\s+/g, ' ').trim()
    if (clean.length <= limit) {
        return clean
    }
    const cut = clean.slice(0, limit - 1)
    const lastSpace = cut.lastIndexOf(' ')
    return `${(lastSpace > limit / 2 ? cut.slice(0, lastSpace) : cut).replace(/[\s,;:.]+$/, '')}…`
}

/** The opening sentence of a markdown summary as plain text. */
function firstSentence(markdown: string): string {
    const opening = markdown.split(/\n\s*\n|\n#/)[0] ?? ''
    const plain = opening
        .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(/[*_`#>]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
    const match = plain.match(/^.+?[.!?](?=\s|$)/)
    return match ? match[0] : plain
}

/** Scout titles often read like commit messages, for example "fix(insights): …". */
function plainTitle(title: string): string {
    return title.replace(/^[a-z]+(\([^)]*\))?!?:\s*/i, '').replace(/^./, (letter) => letter.toUpperCase())
}

const INSIGHT_LINK = /\/insights\/([A-Za-z0-9]{8})(?![A-Za-z0-9])/

function reportChart(report: FeedScoutReport, title: string): ReportChartApi | null {
    if (report.charts?.length) {
        return report.charts[0]
    }
    const shortId = report.summary?.match(INSIGHT_LINK)?.[1]
    return shortId
        ? { chart_id: `insight-${shortId}`, title, query: { kind: NodeKind.SavedInsightNode, shortId }, size: 'medium' }
        : null
}

function scoutPost(report: FeedScoutReport): TodayFeedPost | null {
    const product = report.scout_name ? DATA_SCOUT_PRODUCTS[report.scout_name] : undefined
    if (!product || !report.scout_name) {
        return null
    }
    const title = plainTitle(report.title ?? '')
    // `summary_lead` keeps a bold "Evidence" label and what follows it, so the full summary is cut here instead.
    const text = shortText(firstSentence(report.summary || report.summary_lead || '') || title)
    if (!text) {
        return null
    }
    const chart = reportChart(report, title)
    return {
        key: `scout:${report.id}`,
        kind: 'scout',
        author: {
            name: `${prettifyScoutSkillName(report.scout_name)} scout`,
            handle: `@${report.scout_name.replace(/^signals-scout-/, '').replace(/-/g, '_')}`,
            product,
        },
        at: report.created_at,
        text,
        to: urls.todayReport(report.id),
        product,
        media: chart ? { type: 'report-chart', chart } : null,
    }
}

export function scoutPosts(reports: FeedScoutReport[], hiddenKeys: Record<string, true>): TodayFeedPost[] {
    return reports
        .filter((report) => !hiddenKeys[`scout:${report.id}`])
        .map(scoutPost)
        .filter((post): post is TodayFeedPost => !!post)
        .slice(0, MAX_SCOUT_POSTS)
}

export function feedDays(today: Dayjs): string[] {
    const days: string[] = []
    for (let daysAgo = FEED_DAYS; daysAgo >= 1; daysAgo--) {
        days.push(today.subtract(daysAgo, 'day').format('YYYY-MM-DD'))
    }
    return days
}

function eventLabel(event: string): string {
    return getCoreFilterDefinition(event, TaxonomicFilterGroupType.Events)?.label ?? event
}

function trendUrl(event: string): string {
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event, name: event }],
            interval: 'day',
            dateRange: { date_from: `-${FEED_DAYS}d` },
        },
    }
    return urls.insightNew({ query })
}

function percent(change: number): string {
    return `${Math.round(Math.abs(change) * 100)}%`
}

interface Change {
    name: string
    series: number[]
    current: number
    previous: number
}

/** Daily totals for each event worth a story, oldest day first. */
function seriesByEvent(counts: DayCount[], days: string[]): Map<string, number[]> {
    const series = new Map<string, number[]>()
    for (const { name, daysAgo, count } of counts) {
        const position = days.length - daysAgo
        const plumbing = name.startsWith('$') && !BUILT_IN_EVENTS_WORTH_A_STORY.has(name)
        if (position < 0 || position >= days.length || plumbing) {
            continue
        }
        const values = series.get(name) ?? Array.from({ length: days.length }, () => 0)
        values[position] += count
        series.set(name, values)
    }
    return series
}

type ScoredChange = Change & { score: number; ratio: number }

function scoreChange(name: string, series: number[]): ScoredChange | null {
    const previous = series.slice(0, -WEEK).reduce((sum, value) => sum + value, 0)
    const current = series.slice(-WEEK).reduce((sum, value) => sum + value, 0)
    if (current + previous < MIN_WEEKLY_VOLUME) {
        return null
    }
    if (previous === 0) {
        return { name, series, current, previous, score: Math.log10(current) * 2, ratio: Infinity }
    }
    if (Math.abs(current - previous) / previous < MIN_CHANGE) {
        return null
    }
    const score = Math.abs(Math.log((current || 1) / previous)) * Math.log10(current + previous)
    return { name, series, current, previous, score, ratio: current / previous }
}

function sameStory(a: ScoredChange, b: ScoredChange): boolean {
    if (a.ratio === b.ratio) {
        return true
    }
    if (!Number.isFinite(a.ratio) || !Number.isFinite(b.ratio)) {
        return false
    }
    return Math.abs(a.ratio - b.ratio) <= SAME_STORY_RATIO * Math.max(a.ratio, b.ratio)
}

/** The events whose last week differs most from the week before, one per story. */
function biggestChanges(
    counts: DayCount[],
    days: string[],
    isHidden: (name: string) => boolean,
    limit: number
): Change[] {
    const candidates = [...seriesByEvent(counts, days)]
        .filter(([name]) => !isHidden(name))
        .map(([name, series]) => scoreChange(name, series))
        .filter((change): change is ScoredChange => !!change)
        .sort((a, b) => b.score - a.score)
    const picked: ScoredChange[] = []
    for (const candidate of candidates) {
        if (picked.length === limit) {
            break
        }
        if (!picked.some((other) => sameStory(other, candidate))) {
            picked.push(candidate)
        }
    }
    return picked
}

export function movementPosts(
    eventCounts: DayCount[],
    days: string[],
    hiddenKeys: Record<string, true>,
    at: string | null = null
): TodayFeedPost[] {
    const key = (event: string): string => `movement:${event}:${days[days.length - WEEK]}`
    return biggestChanges(eventCounts, days, (event) => !!hiddenKeys[key(event)], MAX_MOVEMENTS).map(
        ({ name: event, series, current, previous }) => {
            const label = eventLabel(event)
            const volume = `${humanFriendlyLargeNumber(current)} events, against ${humanFriendlyLargeNumber(previous)} the week before.`
            const text =
                previous === 0
                    ? `${label} started this week, with ${humanFriendlyLargeNumber(current)} events so far.`
                    : current === 0
                      ? `${label} had no events this week. ${volume}`
                      : `${label} is ${current > previous ? 'up' : 'down'} ${percent((current - previous) / previous)} this week. ${volume}`
            return {
                key: key(event),
                kind: 'movement',
                author: PRODUCT_ANALYTICS,
                at,
                text: shortText(text),
                to: trendUrl(event),
                media: { type: 'chart', label, current, previous, series, days },
            }
        }
    )
}

const WATCH_CATEGORY_TEXT: Record<string, string> = {
    failure: 'Something failed for this person.',
    struggle: 'This person struggled.',
    revenue: 'A revenue moment.',
}

function pathOf(url: string | null): string | null {
    try {
        return url ? new URL(url).pathname : null
    } catch {
        return null
    }
}

export function replayPosts(
    replayPicks: HighlightFeedItemApi[],
    rageSession: RageSession | null,
    hiddenKeys: Record<string, true>
): TodayFeedPost[] {
    const picks = replayPicks
        .filter((pick) => pick.reason.kind === 'embedding_pick' && !hiddenKeys[`replay:${pick.observation.session_id}`])
        .slice(0, MAX_REPLAYS)
    if (picks.length > 0) {
        return picks.map(({ observation, reason }) => {
            const summary = highlightPickSummary(observation)
            const similar = reason.affected_people ?? 0
            return {
                key: `replay:${observation.session_id}`,
                kind: 'replay',
                author: SESSION_REPLAY,
                at: observation.created_at ?? null,
                text: shortText(
                    [
                        summary.title.endsWith('.') ? summary.title : `${summary.title}.`,
                        reason.watch_category ? WATCH_CATEGORY_TEXT[reason.watch_category] : '',
                        similar > 1 ? `${humanFriendlyLargeNumber(similar)} people saw something like this.` : '',
                    ]
                        .filter(Boolean)
                        .join(' ')
                ),
                to: urls.replaySingle(observation.session_id),
                media: { type: 'replay', sessionId: observation.session_id, page: null, caption: summary.person },
            }
        })
    }
    if (rageSession && rageSession.clicks >= MIN_RAGE_CLICKS && !hiddenKeys[`replay:${rageSession.sessionId}`]) {
        const page = pathOf(rageSession.url)
        return [
            {
                key: `replay:${rageSession.sessionId}`,
                kind: 'replay',
                author: SESSION_REPLAY,
                at: rageSession.startedAt,
                text: shortText(
                    `Someone rage clicked ${rageSession.clicks} times${page ? ` on ${page}` : ''}. No session had more rage clicks in the last 7 days.`
                ),
                to: urls.replaySingle(rageSession.sessionId),
                media: {
                    type: 'replay',
                    sessionId: rageSession.sessionId,
                    page,
                    caption: `${rageSession.clicks} rage clicks`,
                },
            },
        ]
    }
    return []
}

interface FeatureSuggestion {
    product: string
    sceneKey: Scene
    displayLabel: string
    used: (context: { team: TeamPublicType | TeamType; events: Set<string>; hasScoutPosts: boolean }) => boolean
    text: string
    description: string
    actionLabel: string
    to: () => string
}

const FEATURE_SUGGESTIONS: FeatureSuggestion[] = [
    {
        product: 'scouts',
        sceneKey: Scene.Inbox,
        displayLabel: 'Scouts',
        used: ({ hasScoutPosts }) => hasScoutPosts,
        text: 'Turn on a scout and it watches your data for you. When a number moves or a session looks odd, it writes a short post here.',
        description: 'Scouts check your data on a schedule and explain what changed.',
        actionLabel: 'Choose scouts',
        to: () => urls.inbox('scouts'),
    },
    {
        product: 'feature_flags',
        sceneKey: Scene.FeatureFlags,
        displayLabel: 'Feature flags',
        used: ({ events }) => events.has('$feature_flag_called'),
        text: 'Create a feature flag to release your next change to 5% of users first. If something breaks, turn it off in one click, with no redeploy.',
        description: 'Roll out changes slowly and turn them off fast.',
        actionLabel: 'Create a flag',
        to: () => urls.featureFlag('new'),
    },
    {
        product: 'experiments',
        sceneKey: Scene.Experiments,
        displayLabel: 'Experiments',
        used: () => false,
        text: 'Not sure a change helps? Run an experiment. PostHog splits your users, tracks the metric you pick and tells you when the result is clear.',
        description: 'Test a change on part of your users before everyone gets it.',
        actionLabel: 'Open experiments',
        to: () => urls.experiments(),
    },
    {
        product: 'ai_observability',
        sceneKey: Scene.AIObservability,
        displayLabel: 'AI observability',
        used: ({ events }) => events.has('$ai_generation') || events.has('$ai_trace'),
        text: 'Building with LLMs? AI observability records each call with its prompt, output, cost and latency, so you can see which prompts fail and what they cost.',
        description: 'Trace LLM calls, tokens and cost.',
        actionLabel: 'Open AI observability',
        to: () => urls.aiObservabilityDashboard(),
    },
    {
        product: 'error_tracking',
        sceneKey: Scene.ErrorTracking,
        displayLabel: 'Error tracking',
        used: ({ team, events }) => !!team.autocapture_exceptions_opt_in || events.has('$exception'),
        text: 'Error tracking groups the exceptions your users hit and links each one to the session where it happened, so you see what they did just before.',
        description: 'Catch exceptions with the session behind them.',
        actionLabel: 'Open error tracking',
        to: () => urls.errorTracking(),
    },
    {
        product: 'session_replay',
        sceneKey: Scene.Replay,
        displayLabel: 'Session replay',
        used: ({ team }) => !!team.session_recording_opt_in,
        text: 'Turn on session replay to watch real sessions. It shows the clicks, scrolls and errors behind a drop in your numbers.',
        description: 'Watch what people did, not only what they clicked.',
        actionLabel: 'Open session replay',
        to: () => urls.replay(),
    },
    {
        product: 'surveys',
        sceneKey: Scene.Surveys,
        displayLabel: 'Surveys',
        used: ({ team, events }) => !!team.surveys_opt_in || events.has('survey shown'),
        text: 'Ask your users a question inside your app with a survey. Each answer links to what that person did, so feedback comes with context.',
        description: 'Collect feedback in your app.',
        actionLabel: 'Create a survey',
        to: () => urls.surveys(),
    },
    {
        product: 'heatmaps',
        sceneKey: Scene.Heatmaps,
        displayLabel: 'Heatmaps',
        used: ({ team, events }) => !!team.heatmaps_opt_in || !events.has('$pageview'),
        text: 'Heatmaps show where people click and how far they scroll on each page. They use the pageviews you already capture.',
        description: 'See clicks and scroll depth for each page.',
        actionLabel: 'Open heatmaps',
        to: () => urls.heatmaps(),
    },
    {
        product: 'logs',
        sceneKey: Scene.Logs,
        displayLabel: 'Logs',
        used: () => false,
        text: 'Send your app logs to PostHog and search them next to your events, errors and recordings. One place answers what went wrong.',
        description: 'Search logs next to the rest of your data.',
        actionLabel: 'Open logs',
        to: () => urls.logs(),
    },
]

function dayIndexOf(today: Dayjs): number {
    return Math.floor(today.valueOf() / 86_400_000)
}

function rotate<T>(items: T[], dayIndex: number): T[] {
    if (items.length === 0) {
        return items
    }
    const start = dayIndex % items.length
    return [...items.slice(start), ...items.slice(0, start)]
}

export function featurePosts(
    team: TeamPublicType | TeamType | null,
    eventCounts: DayCount[],
    hasScoutPosts: boolean,
    hiddenKeys: Record<string, true>,
    dayIndex: number
): TodayFeedPost[] {
    if (!team) {
        return []
    }
    const events = new Set(eventCounts.map(({ name }) => name))
    const available = FEATURE_SUGGESTIONS.filter(
        (suggestion) =>
            !hiddenKeys[`feature:${suggestion.product}`] &&
            !suggestion.used({ team, events, hasScoutPosts }) &&
            !getProductAccessDisabledReason(suggestion)
    )
    // Scouts fill the feed, so a project without them sees that suggestion first.
    const [first, ...rest] = available
    const ordered = first?.product === 'scouts' ? [first, ...rotate(rest, dayIndex)] : rotate(available, dayIndex)
    return ordered.slice(0, MAX_FEATURE_POSTS).map((suggestion) => ({
        key: `feature:${suggestion.product}`,
        kind: 'feature',
        author: POSTHOG,
        at: null,
        text: shortText(suggestion.text),
        to: suggestion.to(),
        product: suggestion.product,
        media: {
            type: 'card',
            title: suggestion.displayLabel,
            description: suggestion.description,
            actionLabel: suggestion.actionLabel,
        },
    }))
}

export function previewPost(
    previews: FeedPreviewFeature[],
    hiddenKeys: Record<string, true>,
    dayIndex: number
): TodayFeedPost | null {
    const [feature] = rotate(
        previews.filter(
            (preview) => preview.stage === 'beta' && !preview.enabled && !hiddenKeys[`preview:${preview.flagKey}`]
        ),
        dayIndex
    )
    return feature
        ? {
              key: `preview:${feature.flagKey}`,
              kind: 'preview',
              author: POSTHOG,
              at: null,
              text: shortText(`New beta: ${feature.name}. Turn it on to try it before everyone else.`),
              to: urls.featurePreview(feature.flagKey),
              media: {
                  type: 'card',
                  title: feature.name,
                  description: feature.description,
                  actionLabel: 'Turn on',
                  enrollFlagKey: feature.flagKey,
              },
          }
        : null
}

export function buildFeed(inputs: TodayFeedInputs): TodayFeedPost[] {
    const days = feedDays(inputs.today)
    const dayIndex = dayIndexOf(inputs.today)
    const scouts = scoutPosts(inputs.scoutReports, inputs.hiddenKeys)
    const movements = movementPosts(
        inputs.eventCounts,
        days,
        inputs.hiddenKeys,
        inputs.today.startOf('day').toISOString()
    )
    const replays = replayPosts(inputs.replayPicks, inputs.rageSession, inputs.hiddenKeys)
    const features = featurePosts(inputs.team, inputs.eventCounts, scouts.length > 0, inputs.hiddenKeys, dayIndex)
    const preview = previewPost(inputs.previews, inputs.hiddenKeys, dayIndex)
    const interleaved = [
        scouts[0],
        replays[0],
        scouts[1],
        features[0],
        scouts[2],
        movements[0],
        scouts[3],
        preview,
        scouts[4],
        replays[1],
        scouts[5],
        features[1],
        scouts[6],
        movements[1],
        scouts[7],
    ]
    return interleaved.filter((post): post is TodayFeedPost => !!post).slice(0, FEED_MAX_POSTS)
}
