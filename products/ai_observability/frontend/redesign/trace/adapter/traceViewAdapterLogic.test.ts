import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { aiObservabilityAIDataLogic } from '../../../aiObservabilityAIDataLogic'
import { aiObservabilityTraceLogic } from '../../../aiObservabilityTraceLogic'
import { makeEvent, makeTrace } from './testFixtures'
import { traceViewAdapterLogic } from './traceViewAdapterLogic'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('../../../utils', () => ({
    ...jest.requireActual('../../../utils'),
    queryEvaluationRuns: jest.fn().mockResolvedValue([]),
}))

const offloadedGeneration = makeEvent({
    id: 'gen-1',
    event: '$ai_generation',
    createdAt: '2026-09-01T10:15:02Z',
    properties: { $ai_trace_id: 'trace-1', $ai_parent_id: 'trace-1' },
})

// The latest generation, so `pickUserVisibleTurn` picks this one for the thread. Carries
// inline input/output so `toThread` produces messages tagged with this event's id.
const answeredGeneration = makeEvent({
    id: 'gen-2',
    event: '$ai_generation',
    createdAt: '2026-09-01T10:15:03Z',
    properties: {
        $ai_trace_id: 'trace-1',
        $ai_parent_id: 'trace-1',
        $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
        $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
    },
})

const unrelatedSpan = makeEvent({
    id: 'span-1',
    event: '$ai_span',
    createdAt: '2026-09-01T10:15:01Z',
    properties: { $ai_trace_id: 'trace-1', $ai_parent_id: 'trace-1' },
})

describe('traceViewAdapterLogic', () => {
    let logic: ReturnType<typeof traceViewAdapterLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.mocked(performQuery).mockResolvedValue({
            results: [makeTrace({ events: [offloadedGeneration, answeredGeneration, unrelatedSpan] })],
        } as any)
        aiObservabilityTraceLogic.mount()
        router.actions.push(urls.aiObservabilityTrace('trace-1'))
        const { query } = aiObservabilityTraceLogic.values
        logic = traceViewAdapterLogic({ traceId: 'trace-1', query })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready' })
    })

    afterEach(() => logic.unmount())

    it('asks the heavy-data loader for a generation when it is selected', async () => {
        await expectLogic(logic, () => logic.actions.selectNode('gen-1')).toDispatchActions([
            (action) =>
                action.type === aiObservabilityAIDataLogic.actionTypes.ensureAIDataLoaded &&
                action.payload.lookups.some((lookup: { eventId: string }) => lookup.eventId === 'gen-1'),
        ])
    })

    it('falls back to the root node when the event id is unknown', async () => {
        await expectLogic(logic, () => logic.actions.selectNode('does-not-exist')).toMatchValues({
            selectedNodeId: 'trace-1',
            canViewInThread: true,
        })
    })

    it('selecting from the thread or timeline switches to spans', async () => {
        logic.actions.setMode('timeline')
        await expectLogic(logic, () => logic.actions.selectAndShowSpans('gen-1')).toMatchValues({
            mode: 'spans',
            selectedNodeId: 'gen-1',
        })
    })

    it.each([
        ['gen-2', 'a generation whose messages the thread carries', true],
        ['span-1', 'a span the thread never mentions', false],
    ])('canViewInThread for %s (%s) is %s', async (nodeId, _description, expected) => {
        await expectLogic(logic, () => logic.actions.selectNode(nodeId)).toMatchValues({ canViewInThread: expected })
    })

    it('clears a search query left over from a shared legacy URL, so it does not silently filter the tree', async () => {
        logic.unmount()
        router.actions.push(urls.aiObservabilityTrace('trace-1', { search: 'does-not-match-anything' }))
        const { query } = aiObservabilityTraceLogic.values
        logic = traceViewAdapterLogic({ traceId: 'trace-1', query })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ status: 'ready' })
        expect(logic.values.tree[0].children.map((child) => child.id)).toEqual(['span-1', 'gen-1', 'gen-2'])
    })

    it.each([
        [
            'the trace is not found',
            () => Promise.resolve({ results: [] } as any),
            'It may have been deleted, or it is outside the retention period.',
        ],
        [
            'the query fails',
            () => Promise.reject(new Error('boom')),
            'Something went wrong while loading it. Try again in a moment.',
        ],
    ])('status is error when %s', async (_description, mockResult, expectedMessage) => {
        logic.unmount()
        jest.mocked(performQuery).mockReset().mockImplementationOnce(mockResult)
        const { query } = aiObservabilityTraceLogic.values
        logic = traceViewAdapterLogic({ traceId: 'trace-1', query })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ status: 'error', errorMessage: expectedMessage })
    })
})
