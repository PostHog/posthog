import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { type ComponentType, type ReactNode } from 'react'

import * as chartHogPng from '@posthog/brand/hoggies/png/chart-hog'
import * as coffeeRunPng from '@posthog/brand/hoggies/png/coffee-run'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCheck, IconChevronDown, IconCrown, IconInfo, IconLock, IconPeople, IconPerson } from '@posthog/icons'
import { LemonModal, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ExplorerHog, HeartHog, StarHog, WavingHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type {
    AchievementDefinitionApi,
    AchievementProgressApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { deriveTrackProgress } from './achievementProgress'
import { isWebAnalyticsAchievementsEnabled } from './gating'
import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'
import { webAnalyticsAchievementsPreferencesLogic } from './webAnalyticsAchievementsPreferencesLogic'

const HedgehogChartHog = pngHoggie(chartHogPng)
const HedgehogCoffeeRun = pngHoggie(coffeeRunPng)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

const RING_TRACK_COLOR = 'var(--border)'
const TIER_COLORS = [
    'var(--color-slate-400)',
    'var(--color-cyan-400)',
    'var(--color-blue-400)',
    'var(--color-violet-400)',
    'var(--color-amber-400)',
]

interface TrackMeta {
    hog: ComponentType<{ className?: string }>
    objective: string
    unit: string
    effortPhrase: (remaining: number, nextName: string) => string
}

const TRACK_META: Record<string, TrackMeta> = {
    streak: {
        hog: HedgehogCoffeeRun,
        objective: 'Open the Web analytics dashboard on consecutive days to build your streak.',
        unit: 'days',
        effortPhrase: (n, next) =>
            `${humanFriendlyLargeNumber(n)} ${pluralize(n, 'day', 'days', false)} until "${next}"`,
    },
    loyalty: {
        hog: HeartHog,
        objective: 'Open Web analytics on many separate days over time.',
        unit: 'days',
        effortPhrase: (n, next) =>
            `Visit ${humanFriendlyLargeNumber(n)} more ${pluralize(n, 'day', 'days', false)} to reach "${next}"`,
    },
    explorer: {
        hog: ExplorerHog,
        objective: 'Slice your data by adding a filter or opening a breakdown on the Web analytics dashboard.',
        unit: 'explorations',
        effortPhrase: (n, next) =>
            `Explore ${humanFriendlyLargeNumber(n)} more ${pluralize(n, 'time', 'times', false)} to reach "${next}"`,
    },
    detective: {
        hog: HedgehogMagnifyingGlass,
        objective: 'Open a session recording from the Web analytics dashboard.',
        unit: 'recordings',
        effortPhrase: (n, next) =>
            `Watch ${humanFriendlyLargeNumber(n)} more ${pluralize(n, 'recording', 'recordings', false)} to reach "${next}"`,
    },
    conversions: {
        hog: StarHog,
        objective: 'Set up conversion goals in Web analytics.',
        unit: 'conversions',
        effortPhrase: (n, next) => `${humanFriendlyLargeNumber(n)} more to reach "${next}"`,
    },
    traffic: {
        hog: HedgehogChartHog,
        objective: 'Grow your pageviews. This climbs automatically as your site gets more traffic.',
        unit: 'pageviews',
        effortPhrase: (n, next) => `${humanFriendlyLargeNumber(n)} more pageviews until "${next}"`,
    },
}

function ProgressRing({
    percent,
    size,
    strokeWidth,
    color,
    children,
}: {
    percent: number
    size: number
    strokeWidth: number
    color: string
    children?: ReactNode
}): JSX.Element {
    const radius = (size - strokeWidth) / 2
    const circumference = 2 * Math.PI * radius
    const offset = circumference * (1 - Math.max(0, Math.min(100, percent)) / 100)
    return (
        <div className="relative inline-flex items-center justify-center shrink-0">
            <svg width={size} height={size} className="-rotate-90">
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke={RING_TRACK_COLOR}
                    strokeWidth={strokeWidth}
                />
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    fill="none"
                    stroke={color}
                    strokeWidth={strokeWidth}
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    strokeDashoffset={offset}
                    className="transition-all duration-700"
                />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">{children}</div>
        </div>
    )
}

function TrackMedallion({
    hog: Hog,
    ringColor,
    colorFraction,
    maxed,
}: {
    hog: ComponentType<{ className?: string }>
    ringColor: string
    colorFraction: number
    maxed: boolean
}): JSX.Element {
    return (
        <div className="relative shrink-0">
            {maxed && (
                <div
                    aria-hidden
                    className="absolute inset-1 rounded-full opacity-30 blur-md animate-pulse"
                    style={{ backgroundColor: ringColor }}
                />
            )}
            <ProgressRing percent={colorFraction * 100} size={84} strokeWidth={6} color={ringColor}>
                <div
                    className="transition-all duration-700"
                    style={{
                        filter: `grayscale(${Math.round((1 - colorFraction) * 100)}%)`,
                        opacity: 0.7 + 0.3 * colorFraction,
                    }}
                >
                    <Hog className="size-14" />
                </div>
            </ProgressRing>
        </div>
    )
}

function TrackLadder({
    track,
    currentStage,
    unlockedAt,
}: {
    track: AchievementDefinitionApi
    currentStage: number
    unlockedAt: Record<string, string>
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 mt-2 border-t pt-2">
            {track.stages.map((stage) => {
                const unlocked = stage.stage <= currentStage
                const isNext = stage.stage === currentStage + 1
                const unlockedTs = unlockedAt[String(stage.stage)]
                return (
                    <div
                        key={stage.stage}
                        className={clsx(
                            'flex items-center gap-2 text-xs',
                            isNext && 'font-semibold',
                            !unlocked && !isNext && 'text-muted'
                        )}
                    >
                        <span className="shrink-0 flex items-center justify-center w-4">
                            {unlocked ? (
                                <IconCheck className="text-success" />
                            ) : isNext ? (
                                <IconChevronDown className="-rotate-90" />
                            ) : (
                                <IconLock className="text-muted" />
                            )}
                        </span>
                        <span className="flex-1 truncate">{stage.name}</span>
                        <span className="text-muted tabular-nums">{humanFriendlyLargeNumber(stage.threshold)}</span>
                        <span className="text-muted shrink-0 w-16 text-right">
                            {unlocked && unlockedTs ? dayjs(unlockedTs).format('MMM D') : ''}
                        </span>
                    </div>
                )
            })}
        </div>
    )
}

function AchievementTrackCard({
    track,
    progress,
    expanded,
    onToggle,
    pulsing,
}: {
    track: AchievementDefinitionApi
    progress?: AchievementProgressApi
    expanded: boolean
    onToggle: () => void
    pulsing: boolean
}): JSX.Element {
    const trackMeta = TRACK_META[track.key]
    const TrackHog = trackMeta?.hog ?? WavingHog
    const { total, currentStage, value, maxed, currentName, nextStage, percent, remaining } = deriveTrackProgress(
        track,
        progress
    )
    const colorFraction = maxed ? 1 : (currentStage + percent / 100) / total
    const tierIndex = Math.min(Math.max(0, maxed ? total - 1 : currentStage - 1), TIER_COLORS.length - 1)
    const tierColor = TIER_COLORS[tierIndex]
    const unit = trackMeta?.unit ?? ''
    const unlockedAt = progress?.unlocked_at ?? {}
    const calculating = track.scope === 'team' && !!progress && progress.last_computed_at === null
    const completedDate = maxed ? unlockedAt[String(total)] : undefined

    const progressTooltip = maxed
        ? `All ${total} stages complete`
        : nextStage
          ? `${value.toLocaleString()} / ${nextStage.threshold.toLocaleString()} ${unit}`.trim()
          : 'Not started'

    return (
        <div
            className={clsx(
                'border rounded-lg p-4 flex flex-col gap-3 transition-shadow',
                maxed ? 'bg-warning-highlight border-warning' : 'bg-surface-primary',
                pulsing && 'animate-pulse ring-2 ring-warning'
            )}
            data-attr={`web-analytics-achievement-${track.key}`}
        >
            <div
                className="flex items-center gap-3 cursor-pointer"
                onClick={onToggle}
                role="button"
                aria-expanded={expanded}
                data-attr={`web-analytics-achievement-${track.key}-toggle`}
            >
                <Tooltip title={progressTooltip}>
                    <span className="inline-flex">
                        <TrackMedallion
                            hog={TrackHog}
                            ringColor={tierColor}
                            colorFraction={colorFraction}
                            maxed={maxed}
                        />
                    </span>
                </Tooltip>
                <div className="flex flex-col gap-1 flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 min-w-0">
                            <span className="font-semibold text-base truncate">{track.display_name}</span>
                            {trackMeta?.objective && (
                                <Tooltip title={trackMeta.objective}>
                                    <IconInfo className="text-muted shrink-0 cursor-help" />
                                </Tooltip>
                            )}
                        </div>
                        <IconChevronDown
                            className={clsx('text-muted shrink-0 transition-transform', expanded && 'rotate-180')}
                        />
                    </div>

                    {maxed ? (
                        <div className="flex flex-col gap-0.5">
                            <div className="flex items-center gap-1.5 text-sm font-semibold text-warning">
                                <IconCrown className="shrink-0" />
                                <span>Highest tier achieved</span>
                            </div>
                            {completedDate && (
                                <span className="text-xs text-muted">
                                    Unlocked {dayjs(completedDate).format('MMM D, YYYY')}
                                </span>
                            )}
                        </div>
                    ) : calculating ? (
                        <div className="text-xs text-muted">Calculating…</div>
                    ) : (
                        <>
                            {currentName && (
                                <div className="text-xs font-semibold" style={{ color: tierColor }}>
                                    {currentName}
                                </div>
                            )}
                            {nextStage && trackMeta && (
                                <div className="text-xs text-secondary">
                                    {trackMeta.effortPhrase(remaining, nextStage.name)}
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>

            {expanded && <TrackLadder track={track} currentStage={currentStage} unlockedAt={unlockedAt} />}
        </div>
    )
}

function AchievementSection({
    title,
    icon,
    tracks,
    progressByTrack,
    expandedTracks,
    pendingTrackKeys,
    onToggleExpanded,
    headerRight,
}: {
    title: string
    icon: ReactNode
    tracks: AchievementDefinitionApi[]
    progressByTrack: Record<string, AchievementProgressApi>
    expandedTracks: string[]
    pendingTrackKeys: Set<string>
    onToggleExpanded: (trackKey: string) => void
    headerRight?: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2 border-b pb-1.5">
                <div className="flex items-center gap-1.5">
                    <span className="text-base text-secondary">{icon}</span>
                    <h4 className="m-0 text-xs font-semibold uppercase tracking-wide text-secondary">{title}</h4>
                </div>
                {headerRight}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {tracks.map((track) => (
                    <AchievementTrackCard
                        key={track.key}
                        track={track}
                        progress={progressByTrack[track.key]}
                        expanded={expandedTracks.includes(track.key)}
                        onToggle={() => onToggleExpanded(track.key)}
                        pulsing={pendingTrackKeys.has(track.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function WebAnalyticsAchievementsModalInner(): JSX.Element {
    const {
        modalOpen,
        definitions,
        sortedUserTracks,
        sortedTeamTracks,
        progressByTrack,
        expandedTracks,
        achievementsLoading,
        pendingTrackKeys,
        unlockedStages,
        totalStages,
    } = useValues(webAnalyticsAchievementsLogic)
    const { closeModal, toggleTrackExpanded } = useActions(webAnalyticsAchievementsLogic)

    return (
        <LemonModal
            isOpen={modalOpen}
            onClose={closeModal}
            title="Web analytics achievements"
            width={820}
            footer={
                <Link
                    to={urls.settings('user-customization', 'web-analytics-achievements')}
                    onClick={closeModal}
                    className="text-xs text-muted"
                >
                    Not interested? Manage in settings →
                </Link>
            }
        >
            {definitions.length === 0 ? (
                <div className="text-muted text-sm py-6 text-center">
                    {achievementsLoading ? 'Loading achievements…' : 'No achievements available yet.'}
                </div>
            ) : (
                <div className="flex flex-col gap-4">
                    {sortedUserTracks.length > 0 && (
                        <AchievementSection
                            title="Your achievements"
                            icon={<IconPerson />}
                            tracks={sortedUserTracks}
                            progressByTrack={progressByTrack}
                            expandedTracks={expandedTracks}
                            pendingTrackKeys={pendingTrackKeys}
                            onToggleExpanded={toggleTrackExpanded}
                            headerRight={
                                <span className="text-xs text-muted">
                                    <span className="font-semibold">{unlockedStages}</span> of {totalStages} stages
                                    unlocked
                                </span>
                            }
                        />
                    )}
                    {sortedTeamTracks.length > 0 && (
                        <AchievementSection
                            title="Team achievements"
                            icon={<IconPeople />}
                            tracks={sortedTeamTracks}
                            progressByTrack={progressByTrack}
                            expandedTracks={expandedTracks}
                            pendingTrackKeys={pendingTrackKeys}
                            onToggleExpanded={toggleTrackExpanded}
                        />
                    )}
                </div>
            )}
        </LemonModal>
    )
}

export function WebAnalyticsAchievementsModal(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { achievementsOptOut } = useValues(webAnalyticsAchievementsPreferencesLogic)
    if (!isWebAnalyticsAchievementsEnabled(featureFlags, achievementsOptOut)) {
        return null
    }
    return <WebAnalyticsAchievementsModalInner />
}
