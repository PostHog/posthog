import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { Dayjs } from 'lib/dayjs'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { type InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { PropertyFilterType, PropertyOperator, type TeamPublicType, type TeamType } from '~/types'

import type { HighlightFeedItemApi } from 'products/replay_vision/frontend/generated/api.schemas'
import { highlightPickSummary } from 'products/replay_vision/frontend/replay_scanners/highlightPickSummary'

export const FEED_DAYS = 14
export const FEED_MAX_POSTS = 15
const WEEK = 7
const MIN_WEEKLY_VOLUME = 200
const MIN_CHANGE = 0.3
const MIN_RAGE_CLICKS = 3
const MAX_MOVEMENTS = 3
const MAX_PAGES = 2
const MAX_REPLAYS = 2
const MAX_TEAMMATE_POSTS = 3
const MAX_PREVIEWS = 2
// Paired events, such as a start and a finish, move by the same ratio and would tell one story twice.
const SAME_STORY_RATIO = 0.15

// Plumbing events move with SDK changes, not with how people use the product.
const BUILT_IN_EVENTS_WORTH_A_STORY = new Set(['$pageview', '$screen', '$rageclick'])

export type TodayFeedKind = 'movement' | 'page' | 'replay' | 'teammate' | 'preview' | 'try'

export interface TodayFeedAuthor {
    name: string
    handle: string
    product?: string
}

export type TodayFeedMedia =
    | { type: 'chart'; label: string; current: number; previous: number; series: number[]; days: string[] }
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

export interface FeedInsight {
    shortId: string
    name: string
    description: string
    createdAt: string
    authorName: string
    authorHandle: string
}

export interface FeedPreviewFeature {
    flagKey: string
    name: string
    description: string
    stage: string
    enabled: boolean
}

export interface TodayFeedInputs {
    team: TeamPublicType | TeamType | null
    today: Dayjs
    eventCounts: DayCount[]
    pageCounts: DayCount[]
    replayPicks: HighlightFeedItemApi[]
    rageSession: RageSession | null
    insights: FeedInsight[]
    previews: FeedPreviewFeature[]
    hiddenKeys: Record<string, true>
}

const PRODUCT_ANALYTICS: TodayFeedAuthor = {
    name: 'Product analytics',
    handle: '@product_analytics',
    product: 'product_analytics',
}
const WEB_ANALYTICS: TodayFeedAuthor = { name: 'Web analytics', handle: '@web_analytics', product: 'web_analytics' }
const SESSION_REPLAY: TodayFeedAuthor = { name: 'Session replay', handle: '@session_replay', product: 'session_replay' }
const POSTHOG: TodayFeedAuthor = { name: 'PostHog', handle: '@posthog' }

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

function trendUrl(event: string, pathname?: string): string {
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event, name: event }],
            interval: 'day',
            dateRange: { date_from: `-${FEED_DAYS}d` },
            properties: pathname
                ? [
                      {
                          key: '$pathname',
                          value: pathname,
                          operator: PropertyOperator.Exact,
                          type: PropertyFilterType.Event,
                      },
                  ]
                : undefined,
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
    score: number
}

/** The names whose last week differs most from the week before, one per story. */
function biggestChanges(
    counts: DayCount[],
    days: string[],
    include: (name: string) => boolean,
    isHidden: (name: string) => boolean,
    limit: number
): Change[] {
    const seriesByName = new Map<string, number[]>()
    for (const { name, daysAgo, count } of counts) {
        const position = days.length - daysAgo
        if (position < 0 || position >= days.length || !include(name)) {
            continue
        }
        const series = seriesByName.get(name) ?? Array.from({ length: days.length }, () => 0)
        series[position] += count
        seriesByName.set(name, series)
    }

    const candidates: (Change & { ratio: number })[] = []
    for (const [name, series] of seriesByName) {
        const previous = series.slice(0, -WEEK).reduce((sum, value) => sum + value, 0)
        const current = series.slice(-WEEK).reduce((sum, value) => sum + value, 0)
        if (current + previous < MIN_WEEKLY_VOLUME || isHidden(name)) {
            continue
        }
        if (previous === 0) {
            candidates.push({ name, series, current, previous, score: Math.log10(current) * 2, ratio: Infinity })
            continue
        }
        if (Math.abs(current - previous) / previous < MIN_CHANGE) {
            continue
        }
        candidates.push({
            name,
            series,
            current,
            previous,
            score: Math.abs(Math.log((current || 1) / previous)) * Math.log10(current + previous),
            ratio: current / previous,
        })
    }

    const picked: typeof candidates = []
    for (const candidate of candidates.sort((a, b) => b.score - a.score)) {
        const sameStory = picked.some(
            ({ ratio }) =>
                ratio === candidate.ratio ||
                (Number.isFinite(ratio) &&
                    Number.isFinite(candidate.ratio) &&
                    Math.abs(ratio - candidate.ratio) <= SAME_STORY_RATIO * Math.max(ratio, candidate.ratio))
        )
        if (!sameStory) {
            picked.push(candidate)
        }
        if (picked.length === limit) {
            break
        }
    }
    return picked
}

function weekKey(days: string[]): string {
    return days[days.length - WEEK]
}

export function movementPosts(
    eventCounts: DayCount[],
    days: string[],
    hiddenKeys: Record<string, true>,
    at: string | null = null
): TodayFeedPost[] {
    const key = (event: string): string => `movement:${event}:${weekKey(days)}`
    return biggestChanges(
        eventCounts,
        days,
        (event) => !event.startsWith('$') || BUILT_IN_EVENTS_WORTH_A_STORY.has(event),
        (event) => !!hiddenKeys[key(event)],
        MAX_MOVEMENTS
    ).map(({ name: event, series, current, previous }) => {
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
            text,
            to: trendUrl(event),
            media: { type: 'chart', label, current, previous, series, days },
        }
    })
}

export function pagePosts(
    pageCounts: DayCount[],
    days: string[],
    hiddenKeys: Record<string, true>,
    at: string | null = null
): TodayFeedPost[] {
    const key = (path: string): string => `page:${path}:${weekKey(days)}`
    return biggestChanges(
        pageCounts,
        days,
        (path) => !!path,
        (path) => !!hiddenKeys[key(path)],
        MAX_PAGES
    ).map(({ name: path, series, current, previous }) => {
        const change = previous === 0 ? 0 : (current - previous) / previous
        const text =
            previous === 0
                ? `${path} is new this week, with ${humanFriendlyLargeNumber(current)} views so far.`
                : current === 0
                  ? `${path} had no views this week.`
                  : `${path} got ${percent(change)} ${change > 0 ? 'more' : 'fewer'} views this week.`
        return {
            key: key(path),
            kind: 'page',
            author: WEB_ANALYTICS,
            at,
            text,
            to: trendUrl('$pageview', path),
            media: { type: 'chart', label: `Views of ${path}`, current, previous, series, days },
        }
    })
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
                text: [
                    reason.watch_category ? WATCH_CATEGORY_TEXT[reason.watch_category] : '',
                    similar > 1 ? `${humanFriendlyLargeNumber(similar)} people saw something like this.` : '',
                ]
                    .filter(Boolean)
                    .join(' '),
                to: urls.replaySingle(observation.session_id),
                media: { type: 'replay', sessionId: observation.session_id, page: null, caption: summary.title },
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
                text: `Someone rage clicked ${rageSession.clicks} times${page ? ` on ${page}` : ''}. No session had more rage clicks in the last 7 days.`,
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

export function teammatePosts(insights: FeedInsight[], hiddenKeys: Record<string, true>): TodayFeedPost[] {
    return insights
        .filter((insight) => !hiddenKeys[`teammate:${insight.shortId}`])
        .slice(0, MAX_TEAMMATE_POSTS)
        .map((insight) => ({
            key: `teammate:${insight.shortId}`,
            kind: 'teammate',
            author: { name: insight.authorName, handle: insight.authorHandle },
            at: insight.createdAt,
            text: 'Saved a new insight.',
            to: urls.insightView(insight.shortId as Parameters<typeof urls.insightView>[0]),
            media: {
                type: 'card',
                title: insight.name,
                description: insight.description,
                actionLabel: 'Open insight',
            },
        }))
}

interface TrySuggestion {
    product: string
    sceneKey: Scene
    displayLabel: string
    used: (team: TeamPublicType | TeamType, events: Set<string>) => boolean
    fits: (events: Set<string>) => boolean
    text: string
    description: string
    to: () => string
}

const hasWebTraffic = (events: Set<string>): boolean => events.has('$pageview')

const TRY_SUGGESTIONS: TrySuggestion[] = [
    {
        product: 'session_replay',
        sceneKey: Scene.Replay,
        displayLabel: 'Session replay',
        used: (team) => !!team.session_recording_opt_in,
        fits: (events) => events.has('$pageview') || events.has('$screen'),
        text: 'Session replay shows how people use your app.',
        description: 'See the clicks, scrolls and errors behind your numbers.',
        to: () => urls.replay(),
    },
    {
        product: 'heatmaps',
        sceneKey: Scene.Heatmaps,
        displayLabel: 'Heatmaps',
        used: (team) => !!team.heatmaps_opt_in,
        fits: hasWebTraffic,
        text: 'Heatmaps show where people click on your pages.',
        description: 'Heatmaps use the pageviews you already capture.',
        to: () => urls.heatmaps(),
    },
    {
        product: 'error_tracking',
        sceneKey: Scene.ErrorTracking,
        displayLabel: 'Error tracking',
        used: (team, events) => !!team.autocapture_exceptions_opt_in || events.has('$exception'),
        fits: () => true,
        text: 'Error tracking finds the errors your users hit.',
        description: 'Each error links to the session where it happened.',
        to: () => urls.errorTracking(),
    },
    {
        product: 'surveys',
        sceneKey: Scene.Surveys,
        displayLabel: 'Surveys',
        used: (team, events) => !!team.surveys_opt_in || events.has('survey shown'),
        fits: hasWebTraffic,
        text: 'Surveys ask your users a question in your app.',
        description: 'Answers link to what each person did.',
        to: () => urls.surveys(),
    },
    {
        product: 'feature_flags',
        sceneKey: Scene.FeatureFlags,
        displayLabel: 'Feature flags',
        used: (_, events) => events.has('$feature_flag_called'),
        fits: () => true,
        text: 'Feature flags release a change to a few users first.',
        description: 'Turn it off in one click if something breaks.',
        to: () => urls.featureFlags(),
    },
]

function pickForDay<T>(items: T[], dayIndex: number): T | undefined {
    return items.length > 0 ? items[dayIndex % items.length] : undefined
}

function dayIndexOf(today: Dayjs): number {
    return Math.floor(today.valueOf() / 86_400_000)
}

export function tryPost(
    team: TeamPublicType | TeamType | null,
    eventCounts: DayCount[],
    hiddenKeys: Record<string, true>,
    dayIndex: number
): TodayFeedPost | null {
    if (!team) {
        return null
    }
    const events = new Set(eventCounts.map(({ name }) => name))
    const suggestion = pickForDay(
        TRY_SUGGESTIONS.filter(
            (candidate) =>
                !hiddenKeys[`try:${candidate.product}`] &&
                !candidate.used(team, events) &&
                candidate.fits(events) &&
                !getProductAccessDisabledReason(candidate)
        ),
        dayIndex
    )
    return suggestion
        ? {
              key: `try:${suggestion.product}`,
              kind: 'try',
              author: POSTHOG,
              at: null,
              text: `${suggestion.text} This project does not use it yet.`,
              to: suggestion.to(),
              product: suggestion.product,
              media: {
                  type: 'card',
                  title: suggestion.displayLabel,
                  description: suggestion.description,
                  actionLabel: `Open ${suggestion.displayLabel.toLowerCase()}`,
              },
          }
        : null
}

export function previewPosts(
    previews: FeedPreviewFeature[],
    hiddenKeys: Record<string, true>,
    dayIndex: number
): TodayFeedPost[] {
    const available = previews.filter(
        (preview) => preview.stage === 'beta' && !preview.enabled && !hiddenKeys[`preview:${preview.flagKey}`]
    )
    const start = available.length > 0 ? dayIndex % available.length : 0
    return [...available.slice(start), ...available.slice(0, start)].slice(0, MAX_PREVIEWS).map((feature) => ({
        key: `preview:${feature.flagKey}`,
        kind: 'preview',
        author: POSTHOG,
        at: null,
        text: `New beta: ${feature.name}. Turn it on to try it before everyone else.`,
        to: urls.featurePreview(feature.flagKey),
        media: {
            type: 'card',
            title: feature.name,
            description: feature.description,
            actionLabel: 'Turn on',
            enrollFlagKey: feature.flagKey,
        },
    }))
}

export function buildFeed(inputs: TodayFeedInputs): TodayFeedPost[] {
    const days = feedDays(inputs.today)
    const dayIndex = dayIndexOf(inputs.today)
    const computedAt = inputs.today.startOf('day').toISOString()
    const movements = movementPosts(inputs.eventCounts, days, inputs.hiddenKeys, computedAt)
    const pages = pagePosts(inputs.pageCounts, days, inputs.hiddenKeys, computedAt)
    const replays = replayPosts(inputs.replayPicks, inputs.rageSession, inputs.hiddenKeys)
    const teammates = teammatePosts(inputs.insights, inputs.hiddenKeys)
    const previews = previewPosts(inputs.previews, inputs.hiddenKeys, dayIndex)
    const interleaved = [
        movements[0],
        replays[0],
        teammates[0],
        pages[0],
        previews[0],
        movements[1],
        tryPost(inputs.team, inputs.eventCounts, inputs.hiddenKeys, dayIndex),
        teammates[1],
        replays[1],
        pages[1],
        movements[2],
        previews[1],
        teammates[2],
    ]
    return interleaved.filter((post): post is TodayFeedPost => !!post).slice(0, FEED_MAX_POSTS)
}
