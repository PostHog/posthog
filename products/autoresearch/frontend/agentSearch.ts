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
    /** One plain line for people: the agent's `headline`, else its `summary`, else a short first clause of its description. */
    summary: string
    agentDescription: string
    modelSpec: IterationTrailApiModelSpec
    /** Holdout AUC of the last kept experiment before this one in the same run. Null for the first experiment. */
    previousKept: number | null
    /** Holdout AUC minus `previousKept`. Null for a crashed or unscored experiment, or when nothing came before. */
    delta: number | null
    /** Best kept holdout AUC after this experiment, across all runs. Never goes down. */
    bestSoFar: number | null
    isLiveModel: boolean
    /** The experiment that produced the newest challenger with a realized score. */
    isScoredAlongside: boolean
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

/** Holdout and realized AUC of one model, and the run that produced it. */
export interface BriefModel {
    runNumber: number | null
    holdoutScore: number | null
    realizedScore: number | null
}

/** What the top of the Agent research tab says: where the live model stands and what comes next. */
export interface StatusBrief {
    /** The newest completed run. Null before any run completes. */
    runNumber: number | null
    /** The newest completed run's plain sentences for people. Empty when the agent wrote none. */
    readerSummary: string
    /** A short line built from data, for when there is no `readerSummary`. */
    factualLine: string
    nextSteps: string[]
    /** The agent's own notes for its next run. They stay behind a click. */
    distillation: string
    recommendedNext: string
    live: BriefModel | null
    /** The newest challenger with a realized score. Null when no challenger has one. */
    scoredAlongside: BriefModel | null
}

export type RunRole = 'live' | 'scored_alongside'

/** The longest experiment title, so that it fits one line at a narrow scene width. */
const TITLE_MAX_LENGTH = 72
const BRIEF_NEXT_STEPS = 3

function firstSentence(text: string): string {
    const trimmed = text.trim()
    const match = trimmed.match(/^.*?[.!?](?=\s|$)/s)
    return match ? match[0] : trimmed
}

function truncate(text: string, maxLength: number): string {
    if (text.length <= maxLength) {
        return text
    }
    const cut = text.slice(0, maxLength - 1)
    const lastSpace = cut.lastIndexOf(' ')
    return `${(lastSpace > maxLength / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`
}

/** A short title from the agent's description: its first clause, never a full paragraph. */
export function experimentTitle(description: string): string {
    const trimmed = description.trim()
    const match = trimmed.match(/^.*?(?:[.!?;:](?=\s|$)|\s[-–—]\s)/s)
    const clause = (match ? match[0] : trimmed).replace(/\s[-–—]\s$|[.;:]$/, '').trim()
    return truncate(clause, TITLE_MAX_LENGTH)
}

/** A run's one-line headline and the rest of its plain summary. */
export function runHeadline(run: AutoresearchTrainingRunApi, runNumber: number): { headline: string; detail: string } {
    const readerSummary = run.reader_summary?.trim() ?? ''
    const headline = run.headline?.trim()
    if (headline) {
        return { headline, detail: readerSummary }
    }
    if (readerSummary) {
        const first = firstSentence(readerSummary)
        return { headline: first, detail: readerSummary.slice(first.length).trim() }
    }
    const best = run.best_holdout_score ?? bestKeptScore(run)
    return { headline: best != null ? `Run ${runNumber} · best ${best.toFixed(3)}` : `Run ${runNumber}`, detail: '' }
}

/** Short labels for the approaches a run ruled out. */
export function ruledOut(run: AutoresearchTrainingRunApi): string[] {
    return (run.summary?.dead_ends ?? [])
        .map((item) => truncate(experimentTitle(item.agent_description ?? ''), 40))
        .filter((label) => label)
}

function bestKeptScore(run: AutoresearchTrainingRunApi): number | null {
    const scores = run.iterations
        .filter((it) => it.status === 'kept' && it.holdout_score != null)
        .map((it) => it.holdout_score as number)
    return scores.length > 0 ? Math.max(...scores) : null
}

function oldestFirst(runs: AutoresearchTrainingRunApi[]): AutoresearchTrainingRunApi[] {
    return [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at))
}

/** The newest challenger with a realized score: the model scored next to the live one. */
export function scoredChallenger(models: AutoresearchModelApi[]): AutoresearchModelApi | null {
    const scored = models.filter((m) => m.role === 'challenger' && m.realized_score != null)
    scored.sort((a, b) => b.created_at.localeCompare(a.created_at))
    return scored[0] ?? null
}

/** The kept experiment that produced a model: in its source run, the kept score nearest the model's holdout AUC. */
function modelIteration(run: AutoresearchTrainingRunApi, model: AutoresearchModelApi | null): number | null {
    if (!model || model.source_training_run !== run.id) {
        return null
    }
    const target = model.holdout_score ?? Infinity
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
    champion: AutoresearchModelApi | null,
    challenger: AutoresearchModelApi | null = null
): AgentSearch {
    const points: SearchPoint[] = []
    const runs: SearchRunBand[] = []
    let best: number | null = null
    oldestFirst(trainingRuns).forEach((run, runIndex) => {
        const runNumber = runIndex + 1
        const liveIteration = modelIteration(run, champion)
        const challengerIteration = modelIteration(run, challenger)
        const iterations = [...run.iterations].sort((a, b) => a.iteration_number - b.iteration_number)
        const firstSeq = points.length + 1
        let previousKept: number | null = null
        for (const it of iterations) {
            const score = it.status === 'crashed' ? null : (it.holdout_score ?? null)
            const keptBefore = previousKept
            if (it.status === 'kept' && score != null) {
                previousKept = score
                if (best == null || score > best) {
                    best = score
                }
            }
            points.push({
                seq: points.length + 1,
                runId: run.id,
                runNumber,
                iterationNumber: it.iteration_number,
                status: it.status,
                holdoutScore: score,
                summary: it.headline?.trim() || it.summary?.trim() || experimentTitle(it.agent_description ?? ''),
                agentDescription: it.agent_description ?? '',
                modelSpec: it.model_spec,
                previousKept: keptBefore,
                delta: score != null && keptBefore != null ? score - keptBefore : null,
                bestSoFar: best,
                isLiveModel: it.iteration_number === liveIteration,
                isScoredAlongside: it.iteration_number === challengerIteration,
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

/** The y range of the chart: the scored points and any reference score with some room, inside [0, 1]. Crashed points sit on its floor. */
export function searchYDomain(points: SearchPoint[], reference: number | null = null): [number, number] {
    const scores = [...points.map((p) => p.holdoutScore), reference].filter((s): s is number => s != null)
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

function briefModel(model: AutoresearchModelApi, runNumbers: Map<string, number>): BriefModel {
    return {
        runNumber: model.source_training_run ? (runNumbers.get(model.source_training_run) ?? null) : null,
        holdoutScore: model.holdout_score ?? null,
        realizedScore: model.realized_score ?? null,
    }
}

function factualLine(live: BriefModel | null, newestRunNumber: number | null, newestBest: number | null): string {
    const parts: string[] = []
    if (!live) {
        parts.push('There is no live model yet.')
    } else if (live.realizedScore != null && live.holdoutScore != null) {
        parts.push(
            `The live model scores ${live.holdoutScore.toFixed(3)} in training and ${live.realizedScore.toFixed(3)} on real outcomes.`
        )
    } else if (live.holdoutScore != null) {
        parts.push(
            `The live model scores ${live.holdoutScore.toFixed(3)} in training. It is not checked on real outcomes yet.`
        )
    }
    if (newestRunNumber != null && newestBest != null) {
        parts.push(`Run ${newestRunNumber} got a best score of ${newestBest.toFixed(3)} in training.`)
    }
    return parts.join(' ')
}

/** The status brief: the newest completed run's plain notes, or a factual line, and the live and scored-alongside models. */
export function statusBrief(
    trainingRuns: AutoresearchTrainingRunApi[],
    champion: AutoresearchModelApi | null,
    challenger: AutoresearchModelApi | null
): StatusBrief | null {
    const ordered = oldestFirst(trainingRuns)
    const runNumbers = new Map(ordered.map((run, index) => [run.id, index + 1]))
    const newestIndex = ordered.map((run) => run.status).lastIndexOf('completed')
    const newest = newestIndex >= 0 ? ordered[newestIndex] : null
    if (!newest && !champion) {
        return null
    }
    const live = champion ? briefModel(champion, runNumbers) : null
    const runNumber = newest ? newestIndex + 1 : null
    return {
        runNumber,
        readerSummary: newest?.reader_summary?.trim() ?? '',
        factualLine: factualLine(live, runNumber, newest ? (newest.best_holdout_score ?? bestKeptScore(newest)) : null),
        nextSteps: (newest?.next_steps ?? []).filter((step) => step.trim()).slice(0, BRIEF_NEXT_STEPS),
        distillation: newest?.summary?.distillation ?? '',
        recommendedNext: newest?.summary?.recommended_next ?? '',
        live,
        scoredAlongside: challenger ? briefModel(challenger, runNumbers) : null,
    }
}

/** Which runs produced the live model and the model scored alongside it. */
export function runRoles(
    champion: AutoresearchModelApi | null,
    challenger: AutoresearchModelApi | null
): Record<string, RunRole> {
    const roles: Record<string, RunRole> = {}
    if (challenger?.source_training_run) {
        roles[challenger.source_training_run] = 'scored_alongside'
    }
    if (champion?.source_training_run) {
        roles[champion.source_training_run] = 'live'
    }
    return roles
}

/** The agent's model spec as key-value rows: the model class first, then its settings. random_state is noise, so it is dropped. */
export function modelSpecRows(spec: unknown): { key: string; value: string }[] {
    if (!spec || typeof spec !== 'object') {
        return []
    }
    const { model_class, model_params } = spec as { model_class?: string; model_params?: Record<string, unknown> }
    const className = (model_class ?? '').split('.').pop() ?? ''
    const rows = className ? [{ key: 'Model', value: className }] : []
    for (const [key, value] of Object.entries(model_params ?? {})) {
        if (key !== 'random_state') {
            rows.push({ key, value: typeof value === 'object' ? JSON.stringify(value) : String(value) })
        }
    }
    return rows
}

/** "+0.021" style label for an experiment's change against the previous kept experiment in its run. */
export function formatDelta(delta: number | null): string | null {
    if (delta == null) {
        return null
    }
    const rounded = Math.round(delta * 1000) / 1000
    if (rounded === 0) {
        return 'No change'
    }
    return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toFixed(3)}`
}
