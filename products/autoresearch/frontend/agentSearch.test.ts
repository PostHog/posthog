import { buildAgentSearch, experimentLogGroups, experimentTitle, runHeadline, statusBrief } from './agentSearch'
import { AutoresearchModelApi, AutoresearchTrainingRunApi, IterationTrailApi } from './generated/api.schemas'

function iteration(
    iteration_number: number,
    status: IterationTrailApi['status'],
    holdout_score: number | null
): IterationTrailApi {
    return { iteration_number, status, holdout_score, model_spec: { model_class: 'x' } } as IterationTrailApi
}

function run(
    id: string,
    created_at: string,
    iterations: IterationTrailApi[],
    overrides: Partial<AutoresearchTrainingRunApi> = {}
): AutoresearchTrainingRunApi {
    return {
        id,
        created_at,
        status: 'completed',
        iterations,
        summary: null,
        ...overrides,
    } as AutoresearchTrainingRunApi
}

// Listed newest first, as the API returns them, to check the helpers order runs by time themselves.
const RUNS = [
    run('run-2', '2026-01-02T00:00:00Z', [
        iteration(1, 'discarded', 0.78),
        iteration(0, 'kept', 0.75),
        iteration(2, 'crashed', null),
        iteration(3, 'kept', 0.82),
    ]),
    run('run-1', '2026-01-01T00:00:00Z', [iteration(0, 'kept', 0.7), iteration(1, 'kept', 0.8)]),
]

describe('buildAgentSearch', () => {
    it('measures each experiment against the previous kept experiment in its own run', () => {
        const { points } = buildAgentSearch(RUNS, null)
        expect(
            points.map((p) => [p.runNumber, p.iterationNumber, p.status, p.delta?.toFixed(2) ?? null, p.bestSoFar])
        ).toEqual([
            [1, 0, 'kept', null, 0.7],
            [1, 1, 'kept', '0.10', 0.8],
            // The first experiment of a later run has no delta, even below an earlier run's best.
            [2, 0, 'kept', null, 0.8],
            // A discarded experiment with a higher score than a kept one does not raise the best.
            [2, 1, 'discarded', '0.03', 0.8],
            [2, 2, 'crashed', null, 0.8],
            [2, 3, 'kept', '0.07', 0.82],
        ])
    })

    it('marks the kept experiment nearest the champion score in its source run as the live model', () => {
        const champion = { source_training_run: 'run-2', holdout_score: 0.75 } as AutoresearchModelApi
        const { points, runs } = buildAgentSearch(RUNS, champion)
        expect(points.filter((p) => p.isLiveModel).map((p) => [p.runId, p.iterationNumber])).toEqual([['run-2', 0]])
        expect(runs.map((r) => [r.runNumber, r.firstSeq, r.lastSeq])).toEqual([
            [1, 1, 2],
            [2, 3, 6],
        ])
    })

    it.each([
        [
            'the agent headline when there is one',
            'Fewer features',
            'Tried fewer features.',
            'Dropped 12 features. AUC fell.',
            'Fewer features',
        ],
        [
            'the agent summary when there is no headline',
            null,
            'Tried fewer features.',
            'Dropped 12 features. AUC fell.',
            'Tried fewer features.',
        ],
        [
            'the first clause of the description otherwise',
            undefined,
            null,
            'Dropped 12 features (v1.2). AUC fell.',
            'Dropped 12 features (v1.2)',
        ],
        [
            'the whole description when it has no sentence end',
            undefined,
            undefined,
            'Dropped 12 features',
            'Dropped 12 features',
        ],
    ])('shows %s as the one-line summary', (_, headline, summary, agent_description, expected) => {
        const it = { ...iteration(0, 'kept', 0.7), headline, summary, agent_description } as IterationTrailApi
        const { points } = buildAgentSearch([run('run-1', '2026-01-01T00:00:00Z', [it])], null)
        expect(points[0].summary).toEqual(expected)
    })
})

describe('experimentLogGroups', () => {
    it('groups by run newest first, with entries newest first and the filter applied', () => {
        const search = buildAgentSearch(RUNS, null)
        expect(
            experimentLogGroups(RUNS, search, 'kept').map((g) => [g.runNumber, g.entries.map((e) => e.iterationNumber)])
        ).toEqual([
            [2, [3, 0]],
            [1, [1, 0]],
        ])
    })
})

describe('experimentTitle', () => {
    it.each([
        ['a label in capitals', 'SHIPPED BUNDLE. Re-ran the final package end to end.', 'SHIPPED BUNDLE'],
        [
            'a clause before a semicolon',
            'Moved cutoffs to midnight; scoring runs then too.',
            'Moved cutoffs to midnight',
        ],
        [
            'a long clause, cut to one line',
            'Retrained the live recipe with every hourly weight and both views of the population before pruning anything',
            'Retrained the live recipe with every hourly weight and both views of…',
        ],
    ])('keeps %s short', (_, description, expected) => {
        expect(experimentTitle(description)).toEqual(expected)
    })
})

describe('runHeadline', () => {
    it.each([
        [
            'the agent headline, with the plain summary as detail',
            { headline: 'Recency won', reader_summary: 'Recent visits mattered. More later.' },
            { headline: 'Recency won', detail: 'Recent visits mattered. More later.' },
        ],
        [
            'the first sentence of the plain summary, with the rest as detail',
            { reader_summary: 'Found why real outcomes lagged. Training used a random time of day.' },
            { headline: 'Found why real outcomes lagged.', detail: 'Training used a random time of day.' },
        ],
        [
            'the run number and best score without one',
            { best_holdout_score: 0.9431 },
            { headline: 'Run 3 · best 0.943', detail: '' },
        ],
    ])('uses %s', (_, overrides, expected) => {
        const r = run('run-1', '2026-01-01T00:00:00Z', [], overrides as Partial<AutoresearchTrainingRunApi>)
        expect(runHeadline(r, 3)).toEqual(expected)
    })
})

describe('statusBrief', () => {
    const champion = {
        role: 'champion',
        source_training_run: 'run-1',
        holdout_score: 0.948,
        realized_score: 0.874,
    } as AutoresearchModelApi

    it('builds a factual line and keeps the agent notes apart when a run has no plain summary', () => {
        const runs = [
            run('run-3', '2026-01-03T00:00:00Z', [], { status: 'running' }),
            run('run-2', '2026-01-02T00:00:00Z', [], {
                best_holdout_score: 0.94,
                summary: { distillation: 'Recency wins', recommended_next: 'Try sessions' } as any,
            }),
            run('run-1', '2026-01-01T00:00:00Z', []),
        ]
        const brief = statusBrief(runs, champion, null)
        expect(brief).toMatchObject({
            runNumber: 2,
            readerSummary: '',
            factualLine:
                'The live model scores 0.948 in training and 0.874 on real outcomes. Run 2 got a best score of 0.940 in training.',
            distillation: 'Recency wins',
            recommendedNext: 'Try sessions',
            live: { runNumber: 1, holdoutScore: 0.948, realizedScore: 0.874 },
            scoredAlongside: null,
        })
    })

    it('reads the plain summary, at most three next steps, and the scored-alongside model', () => {
        const runs = [
            run('run-2', '2026-01-02T00:00:00Z', [], {
                reader_summary: 'Run 2 found part of the reason.',
                next_steps: ['One', ' ', 'Two', 'Three', 'Four'],
            } as Partial<AutoresearchTrainingRunApi>),
            run('run-1', '2026-01-01T00:00:00Z', []),
        ]
        const challenger = {
            role: 'challenger',
            source_training_run: 'run-2',
            holdout_score: 0.94,
            realized_score: 0.893,
        } as AutoresearchModelApi
        expect(statusBrief(runs, champion, challenger)).toMatchObject({
            readerSummary: 'Run 2 found part of the reason.',
            nextSteps: ['One', 'Two', 'Three'],
            scoredAlongside: { runNumber: 2, holdoutScore: 0.94, realizedScore: 0.893 },
        })
    })
})
