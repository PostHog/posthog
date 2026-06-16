import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonModal, Tooltip } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type {
    AchievementDefinitionApi,
    AchievementProgressApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { isWebAnalyticsAchievementsEnabled } from './gating'
import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'

const TRACK_EMOJI: Record<string, string> = {
    hog_streak: '🔥',
    loyal_hog: '🦔',
    data_hog: '📊',
    detective_hog: '🔍',
    goal_hog: '🎯',
    mighty_hog: '📈',
}

function StageNode({
    name,
    threshold,
    number,
    state,
}: {
    name: string
    threshold: number
    number: number
    state: 'unlocked' | 'next' | 'locked'
}): JSX.Element {
    return (
        <Tooltip title={`${name} · ${threshold.toLocaleString()}`}>
            <div className="flex flex-col items-center gap-1 flex-1 min-w-0">
                <div
                    className={clsx(
                        'size-6 rounded-full flex items-center justify-center text-[11px] font-semibold',
                        state === 'unlocked' && 'bg-success text-white',
                        state === 'next' && 'border-2 border-success text-success',
                        state === 'locked' && 'border border-secondary text-muted'
                    )}
                >
                    {state === 'unlocked' ? '✓' : number}
                </div>
                <span className={clsx('text-[10px] truncate w-full text-center', state === 'locked' && 'text-muted')}>
                    {name}
                </span>
            </div>
        </Tooltip>
    )
}

function AchievementTrackCard({
    track,
    progress,
}: {
    track: AchievementDefinitionApi
    progress?: AchievementProgressApi
}): JSX.Element {
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

    return (
        <div className="border rounded-lg p-4 flex flex-col gap-3" data-attr={`web-analytics-achievement-${track.key}`}>
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xl leading-none">{TRACK_EMOJI[track.key] ?? '🦔'}</span>
                    <span className="font-semibold truncate">{track.display_name}</span>
                </div>
                {maxed ? (
                    <span className="shrink-0 text-xs font-semibold rounded-full px-2 py-0.5 bg-success text-white">
                        Complete
                    </span>
                ) : currentName ? (
                    <span className="shrink-0 text-xs font-semibold rounded-full px-2 py-0.5 border border-success text-success">
                        {currentName}
                    </span>
                ) : (
                    <span className="shrink-0 text-xs text-muted">Not started</span>
                )}
            </div>

            <div className="text-xs text-secondary">{track.description}</div>

            <div className="flex items-start gap-1">
                {track.stages.map((stage) => (
                    <StageNode
                        key={stage.stage}
                        name={stage.name}
                        threshold={stage.threshold}
                        number={stage.stage}
                        state={
                            stage.stage <= currentStage
                                ? 'unlocked'
                                : stage.stage === currentStage + 1
                                  ? 'next'
                                  : 'locked'
                        }
                    />
                ))}
            </div>

            <div className="flex flex-col gap-1">
                <LemonProgress percent={percent} strokeColor="var(--success)" bgColor="var(--border)" />
                <div className="text-[11px] text-muted">
                    {nextStage
                        ? `${value.toLocaleString()} / ${nextStage.threshold.toLocaleString()} → ${nextStage.name}`
                        : `All ${total} stages unlocked 🎉`}
                </div>
            </div>
        </div>
    )
}

function AchievementSection({
    title,
    tracks,
    progressByTrack,
}: {
    title: string
    tracks: AchievementDefinitionApi[]
    progressByTrack: Record<string, AchievementProgressApi>
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h4 className="m-0 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h4>
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
                    <div className="text-sm text-secondary">
                        <span className="font-semibold">{unlockedStages}</span> of {totalStages} stages unlocked across{' '}
                        {definitions.length} tracks — keep coming back to climb every one. 🦔
                    </div>
                    {userTracks.length > 0 && (
                        <AchievementSection
                            title="Your progress"
                            tracks={userTracks}
                            progressByTrack={progressByTrack}
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
