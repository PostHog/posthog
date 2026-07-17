import type {
    AchievementDefinitionApi,
    AchievementProgressApi,
    AchievementStageApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

export interface TrackProgress {
    total: number
    currentStage: number
    value: number
    maxed: boolean
    currentName: string | null
    nextStage: AchievementStageApi | null
    percent: number
    remaining: number
    fractionRemaining: number
}

export function deriveTrackProgress(track: AchievementDefinitionApi, progress?: AchievementProgressApi): TrackProgress {
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
    const remaining = nextStage ? Math.max(0, nextStage.threshold - value) : 0
    const fractionRemaining = maxed ? 0 : 1 - percent / 100
    return {
        total,
        currentStage,
        value,
        maxed,
        currentName,
        nextStage,
        percent,
        remaining,
        fractionRemaining,
    }
}
