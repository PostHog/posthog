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

export const FEED_DAYS = 14
export const FEED_MAX_ITEMS = 6
const WEEK = 7
const MIN_WEEKLY_VOLUME = 200
const MIN_CHANGE = 0.3
const MIN_RAGE_CLICKS = 3
const MAX_MOVEMENTS = 2
const MAX_REPLAYS = 2
// Paired events, such as a start and a finish, move by the same ratio and would tell one story twice.
const SAME_STORY_RATIO = 0.15

// Plumbing events move with SDK changes, not with how people use the product.
const BUILT_IN_EVENTS_WORTH_A_STORY = new Set(['$pageview', '$screen', '$rageclick'])

export type TodayFeedKind = 'movement' | 'replay' | 'try' | 'preview'

export interface TodayFeedItem {
    key: string
    kind: TodayFeedKind
    label: string
    title: string
    facts: string[]
    to: string
    product?: string
    series?: number[]
    seriesLabels?: string[]
}

export interface EventDayCount {
    event: string
    daysAgo: number
    count: number
}

export interface RageSession {
    sessionId: string
    clicks: number
    url: string | null
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
    days: string[]
    eventCounts: EventDayCount[]
    replayPicks: HighlightFeedItemApi[]
    rageSession: RageSession | null
    previews: FeedPreviewFeature[]
    hiddenKeys: Record<string, true>
    dayIndex: number
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

export function movementItems(
    eventCounts: EventDayCount[],
    days: string[],
    hiddenKeys: Record<string, true>
): TodayFeedItem[] {
    const seriesByEvent = new Map<string, number[]>()
    for (const { event, daysAgo, count } of eventCounts) {
        const position = days.length - daysAgo
        if (
            position < 0 ||
            position >= days.length ||
            (event.startsWith('$') && !BUILT_IN_EVENTS_WORTH_A_STORY.has(event))
        ) {
            continue
        }
        const series = seriesByEvent.get(event) ?? Array.from({ length: days.length }, () => 0)
        series[position] += count
        seriesByEvent.set(event, series)
    }

    const weekStart = days[days.length - WEEK]
    const candidates: { item: TodayFeedItem; score: number; ratio: number }[] = []
    for (const [event, series] of seriesByEvent) {
        const previous = series.slice(0, -WEEK).reduce((sum, value) => sum + value, 0)
        const current = series.slice(-WEEK).reduce((sum, value) => sum + value, 0)
        if (current + previous < MIN_WEEKLY_VOLUME) {
            continue
        }
        const key = `movement:${event}:${weekStart}`
        if (hiddenKeys[key]) {
            continue
        }
        const name = eventLabel(event)
        const base = {
            key,
            kind: 'movement' as const,
            label: 'In your data',
            to: trendUrl(event),
            series,
            seriesLabels: days,
        }
        if (previous === 0) {
            candidates.push({
                item: {
                    ...base,
                    title: `${name} started this week, with ${humanFriendlyLargeNumber(current)} events so far`,
                    facts: ['None in the week before'],
                },
                score: Math.log10(current) * 2,
                ratio: Infinity,
            })
            continue
        }
        const change = (current - previous) / previous
        if (Math.abs(change) < MIN_CHANGE) {
            continue
        }
        candidates.push({
            item: {
                ...base,
                title:
                    current === 0
                        ? `${name} had no events this week`
                        : `${name} is ${change > 0 ? 'up' : 'down'} ${percent(change)} this week`,
                facts: [
                    `${humanFriendlyLargeNumber(current)} events, against ${humanFriendlyLargeNumber(previous)} the week before`,
                ],
            },
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
        if (picked.length === MAX_MOVEMENTS) {
            break
        }
    }
    return picked.map(({ item }) => item)
}

const WATCH_CATEGORY_FACTS: Record<string, string> = {
    failure: 'Something failed for this person',
    struggle: 'This person struggled',
    revenue: 'A revenue moment',
}

export function replayItems(
    replayPicks: HighlightFeedItemApi[],
    rageSession: RageSession | null,
    hiddenKeys: Record<string, true>
): TodayFeedItem[] {
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
                label: 'Worth watching',
                title: summary.title,
                facts: [
                    reason.watch_category ? WATCH_CATEGORY_FACTS[reason.watch_category] : summary.scannerName,
                    similar > 1 ? `${humanFriendlyLargeNumber(similar)} people saw something like this` : '',
                ].filter(Boolean),
                to: urls.replaySingle(observation.session_id),
                product: 'replay',
            }
        })
    }
    if (rageSession && rageSession.clicks >= MIN_RAGE_CLICKS && !hiddenKeys[`replay:${rageSession.sessionId}`]) {
        let page: string | null = null
        try {
            page = rageSession.url ? new URL(rageSession.url).pathname : null
        } catch {
            page = null
        }
        return [
            {
                key: `replay:${rageSession.sessionId}`,
                kind: 'replay',
                label: 'Worth watching',
                title: `Someone rage clicked ${rageSession.clicks} times in one session`,
                facts: [page ? `On ${page}` : '', 'Most rage clicks in a session in the last 7 days'].filter(Boolean),
                to: urls.replaySingle(rageSession.sessionId),
                product: 'replay',
            },
        ]
    }
    return []
}

interface TrySuggestion {
    product: string
    sceneKey: Scene
    displayLabel: string
    used: (team: TeamPublicType | TeamType, events: Set<string>) => boolean
    fits: (events: Set<string>) => boolean
    title: string
    fact: string
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
        title: 'Watch how people use your app with session replay',
        fact: 'See the clicks, scrolls and errors behind your numbers',
        to: () => urls.replay(),
    },
    {
        product: 'heatmaps',
        sceneKey: Scene.Heatmaps,
        displayLabel: 'Heatmaps',
        used: (team) => !!team.heatmaps_opt_in,
        fits: hasWebTraffic,
        title: 'See where people click on your pages with heatmaps',
        fact: 'Heatmaps use the pageviews you already capture',
        to: () => urls.heatmaps(),
    },
    {
        product: 'error_tracking',
        sceneKey: Scene.ErrorTracking,
        displayLabel: 'Error tracking',
        used: (team, events) => !!team.autocapture_exceptions_opt_in || events.has('$exception'),
        fits: () => true,
        title: 'Find the errors your users hit with error tracking',
        fact: 'Each error links to the session where it happened',
        to: () => urls.errorTracking(),
    },
    {
        product: 'surveys',
        sceneKey: Scene.Surveys,
        displayLabel: 'Surveys',
        used: (team, events) => !!team.surveys_opt_in || events.has('survey shown'),
        fits: hasWebTraffic,
        title: 'Ask your users a question in your app with surveys',
        fact: 'Answers link to what each person did',
        to: () => urls.surveys(),
    },
    {
        product: 'feature_flags',
        sceneKey: Scene.FeatureFlags,
        displayLabel: 'Feature flags',
        used: (_, events) => events.has('$feature_flag_called'),
        fits: () => true,
        title: 'Release your next change to a few users first with feature flags',
        fact: 'Turn it off in one click if something breaks',
        to: () => urls.featureFlags(),
    },
]

function pickForDay<T>(items: T[], dayIndex: number): T | undefined {
    return items.length > 0 ? items[dayIndex % items.length] : undefined
}

export function tryItem(
    team: TeamPublicType | TeamType | null,
    eventCounts: EventDayCount[],
    hiddenKeys: Record<string, true>,
    dayIndex: number
): TodayFeedItem | null {
    if (!team) {
        return null
    }
    const events = new Set(eventCounts.map(({ event }) => event))
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
              label: 'Try this',
              title: suggestion.title,
              facts: [suggestion.fact],
              to: suggestion.to(),
              product: suggestion.product,
          }
        : null
}

export function previewItem(
    previews: FeedPreviewFeature[],
    hiddenKeys: Record<string, true>,
    dayIndex: number
): TodayFeedItem | null {
    const feature = pickForDay(
        previews.filter(
            (preview) => preview.stage === 'beta' && !preview.enabled && !hiddenKeys[`preview:${preview.flagKey}`]
        ),
        dayIndex
    )
    return feature
        ? {
              key: `preview:${feature.flagKey}`,
              kind: 'preview',
              label: 'New in PostHog',
              title: feature.name,
              facts: [feature.description].filter(Boolean),
              to: urls.featurePreview(feature.flagKey),
          }
        : null
}

export function buildFeed(inputs: TodayFeedInputs): TodayFeedItem[] {
    const [firstMovement, secondMovement] = movementItems(inputs.eventCounts, inputs.days, inputs.hiddenKeys)
    const [firstReplay, secondReplay] = replayItems(inputs.replayPicks, inputs.rageSession, inputs.hiddenKeys)
    const interleaved = [
        firstMovement,
        firstReplay,
        previewItem(inputs.previews, inputs.hiddenKeys, inputs.dayIndex),
        secondMovement,
        tryItem(inputs.team, inputs.eventCounts, inputs.hiddenKeys, inputs.dayIndex),
        secondReplay,
    ]
    return interleaved.filter((item): item is TodayFeedItem => !!item).slice(0, FEED_MAX_ITEMS)
}
