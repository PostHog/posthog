import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { type ComponentType, type ReactNode, useEffect } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonModal, Tooltip } from '@posthog/lemon-ui'

import {
    DetectiveHog,
    ExplorerHog,
    GraphsHog,
    HeartHog,
    RunningHog,
    StarHog,
    WavingHog,
} from 'lib/components/hedgehogs'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type {
    AchievementDefinitionApi,
    AchievementProgressApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { isWebAnalyticsAchievementsEnabled } from './gating'
import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'

const RING_TRACK_COLOR = 'var(--border)'
const RING_ACTIVE_COLOR = 'var(--success)'
const RING_COMPLETE_COLOR = 'var(--warning)'

const TRACK_META: Record<string, { hog: ComponentType<{ className?: string }>; objective: string }> = {
    streak: {
        hog: RunningHog,
        objective: 'Open the Web analytics dashboard on consecutive days to build your streak.',
    },
    loyalty: { hog: HeartHog, objective: 'Open Web analytics on many separate days over time.' },
    explorer: {
        hog: ExplorerHog,
        objective: 'Slice your data by adding a filter or opening a breakdown on the Web analytics dashboard.',
    },
    detective: { hog: DetectiveHog, objective: 'Open a session recording from the Web analytics dashboard.' },
    conversions: { hog: StarHog, objective: 'Set up conversion goals in Web analytics.' },
    traffic: {
        hog: GraphsHog,
        objective: 'Grow your pageviews. This climbs automatically as your site gets more traffic.',
    },
}

function formatCompact(n: number): string {
    if (n >= 1_000_000) {
        return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
    }
    return n.toLocaleString()
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
    filled,
    total,
    colorFraction,
    maxed,
}: {
    hog: ComponentType<{ className?: string }>
    filled: number
    total: number
    colorFraction: number
    maxed: boolean
}): JSX.Element {
    const levelPercent = total ? (filled / total) * 100 : 0
    return (
        <div className="relative shrink-0">
            {maxed && (
                <div
                    aria-hidden
                    className="absolute inset-1 rounded-full bg-warning opacity-30 blur-md animate-pulse"
                />
            )}
            <ProgressRing
                percent={levelPercent}
                size={84}
                strokeWidth={6}
                color={maxed ? RING_COMPLETE_COLOR : RING_ACTIVE_COLOR}
            >
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

function AchievementTrackCard({
    track,
    progress,
}: {
    track: AchievementDefinitionApi
    progress?: AchievementProgressApi
}): JSX.Element {
    const trackMeta = TRACK_META[track.key]
    const TrackHog = trackMeta?.hog ?? WavingHog
    const total = track.stages.length
    const currentStage = progress?.current_stage ?? 0
    const value = progress?.progress_value ?? 0
    const maxed = currentStage >= total
    const currentName = currentStage > 0 ? track.stages[currentStage - 1].name : null
    const nextStage = maxed ? null : track.stages[currentStage]
    const prevThreshold = currentStage > 0 ? track.stages[currentStage - 1].threshold : 0
    const percent = nextStage
        ? Math.max(0, Math.min(100, ((value - prevThreshold) / (nextStage.threshold - prevThreshold)) * 100))
        : 100
    const colorFraction = maxed ? 1 : (currentStage + percent / 100) / total

    let statusPill: JSX.Element
    if (maxed) {
        statusPill = (
            <span className="shrink-0 text-xs font-semibold rounded-full px-2 py-0.5 bg-warning text-white">
                Complete
            </span>
        )
    } else if (currentStage > 0) {
        const goalThreshold = nextStage?.threshold ?? 0
        const abbreviated = value >= 1_000_000 || goalThreshold >= 1_000_000
        statusPill = (
            <Tooltip title={abbreviated ? `${value.toLocaleString()} / ${goalThreshold.toLocaleString()}` : undefined}>
                <span className="shrink-0 text-xs font-semibold rounded-full px-2 py-0.5 border border-success text-success">
                    {formatCompact(value)} / {formatCompact(goalThreshold)}
                </span>
            </Tooltip>
        )
    } else {
        statusPill = <span className="shrink-0 text-xs text-muted">Not started</span>
    }

    return (
        <div
            className="border rounded-lg p-4 flex flex-col gap-3 bg-surface-primary"
            data-attr={`web-analytics-achievement-${track.key}`}
        >
            <div className="flex items-center gap-3">
                <TrackMedallion
                    hog={TrackHog}
                    filled={currentStage}
                    total={total}
                    colorFraction={colorFraction}
                    maxed={maxed}
                />
                <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 min-w-0">
                            <span className="font-semibold text-base truncate">{track.display_name}</span>
                            {trackMeta?.objective && (
                                <Tooltip title={trackMeta.objective}>
                                    <IconInfo className="text-muted shrink-0 cursor-help" />
                                </Tooltip>
                            )}
                        </div>
                        {statusPill}
                    </div>
                    {currentName && (
                        <div className={clsx('text-xs font-semibold', maxed ? 'text-warning' : 'text-success')}>
                            {currentName}
                        </div>
                    )}
                    <div className="text-xs text-secondary">{track.description}</div>
                </div>
            </div>
        </div>
    )
}

function AchievementSection({
    title,
    tracks,
    progressByTrack,
    headerRight,
}: {
    title: string
    tracks: AchievementDefinitionApi[]
    progressByTrack: Record<string, AchievementProgressApi>
    headerRight?: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-2">
                <h4 className="m-0 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h4>
                {headerRight}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {tracks.map((track) => (
                    <AchievementTrackCard key={track.key} track={track} progress={progressByTrack[track.key]} />
                ))}
            </div>
        </div>
    )
}

function WebAnalyticsAchievementsModalInner(): JSX.Element {
    const { modalOpen, definitions, progressByTrack, uncelebratedPending, achievementsLoading } =
        useValues(webAnalyticsAchievementsLogic)
    const { closeModal, acknowledgeCelebration } = useActions(webAnalyticsAchievementsLogic)
    const { trigger, HogfettiComponent } = useHogfetti({ count: 80, duration: 2500 })

    useEffect(() => {
        if (!modalOpen || uncelebratedPending.length === 0) {
            return
        }
        uncelebratedPending.forEach((entry) => {
            trigger()
            acknowledgeCelebration(entry.track_key, entry.stage)
        })
    }, [modalOpen, uncelebratedPending, trigger, acknowledgeCelebration])

    const userTracks = definitions.filter((track) => track.scope === 'user')
    const teamTracks = definitions.filter((track) => track.scope === 'team')
    const unlockedStages = definitions.reduce((sum, track) => sum + (progressByTrack[track.key]?.current_stage ?? 0), 0)
    const totalStages = definitions.reduce((sum, track) => sum + track.stages.length, 0)

    return (
        <LemonModal isOpen={modalOpen} onClose={closeModal} title="Web analytics achievements" width={820}>
            <HogfettiComponent />
            {definitions.length === 0 ? (
                <div className="text-muted text-sm py-6 text-center">
                    {achievementsLoading ? 'Loading achievements…' : 'No achievements available yet.'}
                </div>
            ) : (
                <div className="flex flex-col gap-4">
                    {userTracks.length > 0 && (
                        <AchievementSection
                            title="Your progress"
                            tracks={userTracks}
                            progressByTrack={progressByTrack}
                            headerRight={
                                <span className="text-xs text-muted">
                                    <span className="font-semibold">{unlockedStages}</span> of {totalStages} stages
                                    unlocked
                                </span>
                            }
                        />
                    )}
                    {teamTracks.length > 0 && (
                        <AchievementSection
                            title="Team progress"
                            tracks={teamTracks}
                            progressByTrack={progressByTrack}
                        />
                    )}
                </div>
            )}
        </LemonModal>
    )
}

export function WebAnalyticsAchievementsModal(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!isWebAnalyticsAchievementsEnabled(featureFlags)) {
        return null
    }
    return <WebAnalyticsAchievementsModalInner />
}
