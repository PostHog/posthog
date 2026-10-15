import { buildAgentSearch, experimentLogGroups, latestAgentNotes } from './agentSearch'
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
    it('measures each experiment against the best kept score before it, across runs', () => {
        const { points } = buildAgentSearch(RUNS, null)
        expect(
            points.map((p) => [p.runNumber, p.iterationNumber, p.status, p.delta?.toFixed(2) ?? null, p.bestSoFar])
        ).toEqual([
            [1, 0, 'kept', null, 0.7],
            [1, 1, 'kept', '0.10', 0.8],
            // The first experiment of a later run compares against the best of the runs before it.
            [2, 0, 'kept', '-0.05', 0.8],
            // A discarded experiment with a higher score than a kept one does not raise the best.
            [2, 1, 'discarded', '-0.02', 0.8],
            [2, 2, 'crashed', null, 0.8],
            [2, 3, 'kept', '0.02', 0.82],
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
            'the first sentence of the description otherwise',
            undefined,
            null,
            'Dropped 12 features (v1.2). AUC fell.',
            'Dropped 12 features (v1.2).',
        ],
        [
            'the first clause of the description, cut to length',
            null,
            null,
            `Dropped ${'very '.repeat(12)}weak features, AUC fell.`,
            `Dropped ${'very '.repeat(10).trim()}…`,
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

    it.each([
        [
            'the run headline',
            { headline: 'Recency won', reader_summary: 'Recent visits mattered. More later.' },
            'Recency won',
        ],
        [
            'the first sentence of the reader summary',
            { headline: null, reader_summary: 'Recent visits mattered. More later.' },
            'Recent visits mattered.',
        ],
        ['the run number', {}, 'Run 1'],
    ])('falls back to %s', (_, overrides, expected) => {
        const runs = [run('run-1', '2026-01-01T00:00:00Z', [], overrides as Partial<AutoresearchTrainingRunApi>)]
        expect(experimentLogGroups(runs, buildAgentSearch(runs, null), 'all')[0].headline).toEqual(expected)
    })
})

describe('latestAgentNotes', () => {
    it('reads the newest completed run that left notes', () => {
        const notes = { distillation: 'Recency wins', recommended_next: 'Try sessions' }
        const runs = [
            run('run-3', '2026-01-03T00:00:00Z', [], { status: 'running' }),
            run('run-2', '2026-01-02T00:00:00Z', [], { summary: { distillation: '', recommended_next: '' } as any }),
            run('run-1', '2026-01-01T00:00:00Z', [], { summary: notes as any }),
        ]
        expect(latestAgentNotes(runs)).toEqual({
            runNumber: 1,
            readerSummary: '',
            nextSteps: [],
            distillation: 'Recency wins',
            recommendedNext: 'Try sessions',
        })
    })

    it('reads the plain notes for people when a run left only those', () => {
        const runs = [
            run('run-1', '2026-01-01T00:00:00Z', [], {
                reader_summary: 'Recent visits predict a purchase best.',
                next_steps: ['Add session length', ' '],
            } as Partial<AutoresearchTrainingRunApi>),
        ]
        expect(latestAgentNotes(runs)).toEqual({
            runNumber: 1,
            readerSummary: 'Recent visits predict a purchase best.',
            nextSteps: ['Add session length'],
            distillation: '',
            recommendedNext: '',
        })
    })
})
