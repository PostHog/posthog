import type {
    AutoresearchIterationStatusEnumApi,
    AutoresearchModelApi,
    AutoresearchTrainingRunApi,
    IterationTrailApiModelSpec,
} from './generated/api.schemas'

/** One experiment the agent ran, placed on the search across every training run. */
export interface SearchPoint {
    /** 1-based position across all runs, oldest first. The chart's x value. */
    seq: number
    runId: string
    /** 1-based run number, oldest first. */
    runNumber: number
    iterationNumber: number
    status: AutoresearchIterationStatusEnumApi
    holdoutScore: number | null
    agentDescription: string
    modelSpec: IterationTrailApiModelSpec
    /** Best kept holdout AUC before this experiment, across all earlier runs too. */
    bestBefore: number | null
    /** Holdout AUC minus `bestBefore`. Null for a crashed or unscored experiment, or when nothing came before. */
    delta: number | null
    /** Best kept holdout AUC after this experiment. Never goes down. */
    bestSoFar: number | null
    isLiveModel: boolean
}

/** The span of one training run on the chart's x axis. */
export interface SearchRunBand {
    runId: string
    runNumber: number
    startedAt: string
    firstSeq: number
    lastSeq: number
}

export interface AgentSearch {
    points: SearchPoint[]
    runs: SearchRunBand[]
}

export type ExperimentLogFilter = 'all' | 'kept' | 'discarded' | 'crashed'

export interface ExperimentLogGroup {
    run: AutoresearchTrainingRunApi
    runNumber: number
    /** Newest first, after the filter. */
    entries: SearchPoint[]
}

export interface AgentNotes {
    runNumber: number
    distillation: string
    recommendedNext: string
}

function oldestFirst(runs: AutoresearchTrainingRunApi[]): AutoresearchTrainingRunApi[] {
    return [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at))
}

/** The kept experiment that produced the champion: in its source run, the kept score nearest the champion's holdout AUC. */
function liveModelIteration(run: AutoresearchTrainingRunApi, champion: AutoresearchModelApi | null): number | null {
    if (!champion || champion.source_training_run !== run.id) {
        return null
    }
    const target = champion.holdout_score ?? Infinity
    let best: { iterationNumber: number; distance: number; score: number } | null = null
    for (const it of run.iterations) {
        if (it.status !== 'kept' || it.holdout_score == null) {
            continue
        }
        const distance = Math.abs(it.holdout_score - target)
        if (!best || distance < best.distance || (distance === best.distance && it.holdout_score > best.score)) {
            best = { iterationNumber: it.iteration_number, distance, score: it.holdout_score }
        }
    }
    return best?.iterationNumber ?? null
}

export function buildAgentSearch(
    trainingRuns: AutoresearchTrainingRunApi[],
    champion: AutoresearchModelApi | null
): AgentSearch {
    const points: SearchPoint[] = []
    const runs: SearchRunBand[] = []
    let best: number | null = null
    oldestFirst(trainingRuns).forEach((run, runIndex) => {
        const runNumber = runIndex + 1
        const liveIteration = liveModelIteration(run, champion)
        const iterations = [...run.iterations].sort((a, b) => a.iteration_number - b.iteration_number)
        const firstSeq = points.length + 1
        for (const it of iterations) {
            const score = it.status === 'crashed' ? null : (it.holdout_score ?? null)
            const bestBefore = best
            if (it.status === 'kept' && score != null && (best == null || score > best)) {
                best = score
            }
            points.push({
                seq: points.length + 1,
                runId: run.id,
                runNumber,
                iterationNumber: it.iteration_number,
                status: it.status,
                holdoutScore: score,
                agentDescription: it.agent_description ?? '',
                modelSpec: it.model_spec,
                bestBefore,
                delta: score != null && bestBefore != null ? score - bestBefore : null,
                bestSoFar: best,
                isLiveModel: it.iteration_number === liveIteration,
            })
        }
        if (points.length >= firstSeq) {
            runs.push({
                runId: run.id,
                runNumber,
                startedAt: run.started_at ?? run.created_at,
                firstSeq,
                lastSeq: points.length,
            })
        }
    })
    return { points, runs }
}

/** The y range of the chart: the scored points with some room, inside [0, 1]. Crashed points sit on its floor. */
export function searchYDomain(points: SearchPoint[]): [number, number] {
    const scores = points.map((p) => p.holdoutScore).filter((s): s is number => s != null)
    if (scores.length === 0) {
        return [0, 1]
    }
    const low = Math.min(...scores)
    const high = Math.max(...scores)
    const pad = Math.max((high - low) * 0.1, 0.01)
    return [Math.max(0, low - pad), Math.min(1, high + pad)]
}

export function experimentLogGroups(
    trainingRuns: AutoresearchTrainingRunApi[],
    search: AgentSearch,
    filter: ExperimentLogFilter
): ExperimentLogGroup[] {
    const pointsByRun = new Map<string, SearchPoint[]>()
    for (const point of search.points) {
        if (filter === 'all' || point.status === filter) {
            pointsByRun.set(point.runId, [...(pointsByRun.get(point.runId) ?? []), point])
        }
    }
    return oldestFirst(trainingRuns)
        .map((run, index) => ({
            run,
            runNumber: index + 1,
            entries: [...(pointsByRun.get(run.id) ?? [])].reverse(),
        }))
        .reverse()
}

/** The newest completed run's notes. Null when no completed run left any. */
export function latestAgentNotes(trainingRuns: AutoresearchTrainingRunApi[]): AgentNotes | null {
    const ordered = oldestFirst(trainingRuns)
    for (let i = ordered.length - 1; i >= 0; i--) {
        const summary = ordered[i].summary
        if (ordered[i].status === 'completed' && (summary?.distillation || summary?.recommended_next)) {
            return {
                runNumber: i + 1,
                distillation: summary.distillation,
                recommendedNext: summary.recommended_next,
            }
        }
    }
    return null
}

/** The agent's model spec (class and hyperparameters), compact. random_state is noise, so it is dropped. */
export function formatModelSpec(spec: unknown): { className: string; params: string } | null {
    if (!spec || typeof spec !== 'object') {
        return null
    }
    const { model_class, model_params } = spec as { model_class?: string; model_params?: Record<string, unknown> }
    const className = (model_class ?? '').split('.').pop() ?? ''
    const params = model_params
        ? Object.entries(model_params)
              .filter(([key]) => key !== 'random_state')
              .map(([key, value]) => `${key}=${value}`)
              .join(', ')
        : ''
    return className || params ? { className, params } : null
}

/** "+0.021 vs best" style label for an experiment's change against the best score before it. */
export function formatDelta(delta: number | null): string | null {
    if (delta == null) {
        return null
    }
    const rounded = Math.round(delta * 1000) / 1000
    if (rounded === 0) {
        return 'Same as best'
    }
    return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toFixed(3)} vs best`
}
