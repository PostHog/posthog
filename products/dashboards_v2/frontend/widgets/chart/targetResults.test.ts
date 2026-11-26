import type { ChartTarget } from './chartSpec'
import { type ChartResult, combineTargetResults } from './targetResults'
import type { QueryFrames } from './useQueryFrames'

const target = (refId: string): ChartTarget => ({ refId, query: { language: 'promql', query: 'up' } })
const TARGETS = [target('A'), target('B')]
const latency: QueryFrames = { status: 'ready', refreshing: false, frames: [{ name: 'p95', fields: [] }] }
const failed = (message: string): QueryFrames => ({ status: 'error', message })
const loading: QueryFrames = { status: 'loading' }

describe('combineTargetResults', () => {
    test.each<{ name: string; results: QueryFrames[]; expected: ChartResult }>([
        {
            name: 'draws the targets that ran and lists the one that failed',
            results: [failed('parse error'), latency],
            expected: {
                status: 'ready',
                refreshing: false,
                frames: [{ name: 'p95', refId: 'B', fields: [] }],
                failures: [{ refId: 'A', message: 'parse error' }],
            },
        },
        {
            name: 'draws a target that answered while another still runs',
            results: [latency, loading],
            expected: {
                status: 'ready',
                refreshing: true,
                frames: [{ name: 'p95', refId: 'A', fields: [] }],
                failures: [],
            },
        },
        {
            name: 'shows an error naming each target when every target failed',
            results: [failed('parse error'), failed('timed out')],
            expected: { status: 'error', message: 'A: parse error B: timed out' },
        },
        {
            name: 'waits while no target has answered',
            results: [failed('parse error'), loading],
            expected: { status: 'loading' },
        },
    ])('$name', ({ results, expected }) => {
        expect(combineTargetResults(TARGETS, results, true)).toEqual(expected)
    })
})
