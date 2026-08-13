import { BuildStatusEnumApi } from 'products/canvas/frontend/generated/api.schemas'
import { TaskRunStatusEnumApi } from 'products/tasks/frontend/generated/api.schemas'

export type GenUIGenerationProgress = {
    buildStatus: BuildStatusEnumApi | null
    runCreatedAt: string | null
    runStage: string | null
    runStatus: string | null
    runUpdatedAt: string | null
}

export type GenUIGenerationProgressView = {
    detail: string
    label: string
}

function formatDuration(durationMs: number): string {
    const totalSeconds = Math.max(0, Math.floor(durationMs / 1000))
    if (totalSeconds < 60) {
        return `${totalSeconds}s`
    }

    const totalMinutes = Math.floor(totalSeconds / 60)
    const seconds = totalSeconds % 60
    if (totalMinutes < 60) {
        return seconds ? `${totalMinutes}m ${seconds}s` : `${totalMinutes}m`
    }

    const hours = Math.floor(totalMinutes / 60)
    const minutes = totalMinutes % 60
    return minutes ? `${hours}h ${minutes}m` : `${hours}h`
}

function formatStage(stage: string): string {
    const words = stage.replaceAll(/[_-]+/g, ' ').trim().toLowerCase()
    return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : ''
}

function getProgressLabel(progress: GenUIGenerationProgress | null): string {
    if (progress?.buildStatus === BuildStatusEnumApi.Queued) {
        return 'Visualization build is queued'
    }
    if (progress?.buildStatus === BuildStatusEnumApi.Building) {
        return 'Building visualization'
    }
    if (progress?.buildStatus === BuildStatusEnumApi.Ready) {
        return 'Publishing visualization'
    }
    if (progress?.runStatus === TaskRunStatusEnumApi.Completed) {
        return 'Preparing visualization build'
    }
    if (
        progress?.runStatus === TaskRunStatusEnumApi.NotStarted ||
        progress?.runStatus === TaskRunStatusEnumApi.Queued
    ) {
        return 'Waiting for generation worker'
    }
    if (progress?.runStatus === TaskRunStatusEnumApi.InProgress) {
        const stage = progress.runStage ? formatStage(progress.runStage) : ''
        return stage || 'Agent is building the visualization'
    }
    return 'Starting visualization generation'
}

export function getGenUIGenerationProgressView(
    progress: GenUIGenerationProgress | null,
    observedAtMs: number,
    nowMs: number
): GenUIGenerationProgressView {
    const runCreatedAtMs = progress?.runCreatedAt ? Date.parse(progress.runCreatedAt) : Number.NaN
    const startedAtMs = Number.isFinite(runCreatedAtMs) ? runCreatedAtMs : observedAtMs
    const elapsed = formatDuration(nowMs - startedAtMs)
    const runUpdatedAtMs = progress?.runUpdatedAt ? Date.parse(progress.runUpdatedAt) : Number.NaN
    const updateDetail = Number.isFinite(runUpdatedAtMs)
        ? nowMs - runUpdatedAtMs < 30_000
            ? 'Updated just now'
            : `Last task update ${formatDuration(nowMs - runUpdatedAtMs)} ago`
        : 'Waiting for the first task update'

    return {
        detail: `Elapsed ${elapsed} · ${updateDetail}`,
        label: getProgressLabel(progress),
    }
}
