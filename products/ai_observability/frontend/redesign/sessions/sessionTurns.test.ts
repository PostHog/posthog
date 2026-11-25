import type { SessionTurnApi, TraceTurnApi } from '../../generated/api.schemas'
import { aiObservabilityTracesTurnsCreateBodyTraceIdsMax as MAX_TRACES } from '../../generated/api.zod'
import type { TraceCellLoad } from '../shared/cellLoads'
import { TURNS_REQUEST_MAX_SPAN_MS, conversationTurns, turnSidesBatches, turnSidesOfRows } from './sessionTurns'
import { makeSessionTurn, makeTraceTurn } from './testFixtures'

const START_MS = Date.parse('2026-09-01T10:00:00Z')

function rowAt(id: string, offsetMs: number): SessionTurnApi {
    return makeSessionTurn({ id, createdAt: new Date(START_MS + offsetMs).toISOString() })
}

describe('sessionTurns', () => {
    it.each([
        [
            'one turn more than a request takes',
            Array.from({ length: MAX_TRACES + 1 }, (_, index) => index * 1000),
            [MAX_TRACES, 1],
        ],
        ['turns as far apart as a request spans', [0, TURNS_REQUEST_MAX_SPAN_MS], [2]],
        ['turns just further apart than a request spans', [0, TURNS_REQUEST_MAX_SPAN_MS + 1], [1, 1]],
    ])('splits %s into requests the read accepts', (_name, offsets, sizes) => {
        const rows = offsets.map((offset, index) => rowAt(`trace-${index}`, offset))

        expect(turnSidesBatches(rows).map((batch) => batch.length)).toEqual(sizes)
    })

    it('answers every requested turn once, and a left out one with null', () => {
        const turn = makeTraceTurn('a')

        expect(turnSidesOfRows([rowAt('a', 0), rowAt('b', 1)], [turn])).toEqual([
            { traceId: 'a', turn },
            { traceId: 'b', turn: null },
        ])
    })

    it.each<[string, TraceCellLoad<TraceTurnApi | null> | undefined, object]>([
        ['not asked for yet', undefined, { sidesStatus: 'loading', input: { kind: 'messages', messages: [] } }],
        ['loading', { status: 'loading' }, { sidesStatus: 'loading' }],
        ['failed', { status: 'error' }, { sidesStatus: 'error', output: { kind: 'messages', messages: [] } }],
        [
            'left out',
            { status: 'ready', value: null },
            { sidesStatus: 'ready', input: { kind: 'messages', messages: [] } },
        ],
        [
            'read',
            { status: 'ready', value: makeTraceTurn('a', { output: null, outputMissingReason: 'timed_out' }) },
            {
                sidesStatus: 'ready',
                input: makeTraceTurn('a').input,
                output: { kind: 'messages', messages: [] },
                missingReasons: { input: null, output: 'timed_out' },
            },
        ],
    ])('shows a turn whose messages are %s', (_name, load, expected) => {
        const row = makeSessionTurn({ id: 'a', firstError: 'boom', waitSlow: true, silenceBeforeMs: 90_000 })
        const sides = new Map(load ? [['a', load]] : [])

        expect(conversationTurns([row], sides)).toEqual([
            expect.objectContaining({
                id: 'a',
                error: 'boom',
                waitMs: row.totals.latencyMs,
                waitSlow: true,
                silenceBeforeMs: 90_000,
                ...expected,
            }),
        ])
    })
})
