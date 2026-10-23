import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { aiObservabilityTraceLogic } from '../../../aiObservabilityTraceLogic'
import { TraceScene } from '../TraceScene'
import { decodeIdSegment, makeEvent, makeNodeDetail, makeTrace, makeTraceResource } from './testFixtures'

const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('../../../utils', () => ({
    ...jest.requireActual('../../../utils'),
    queryEvaluationRuns: jest.fn().mockResolvedValue([]),
}))

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const NODE_URL = '/api/projects/:team_id/ai_observability/traces/:id/nodes/:node_id/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const answeredGeneration = makeNodeDetail({
    id: 'gen-2',
    properties: {
        $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
        $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
    },
    ioKeys: { input: '$ai_input', output: '$ai_output_choices' },
})
let nodeRequests: string[] = []
const nodeMock = {
    [NODE_URL]: ({ params }: { params: Record<string, unknown> }) => {
        const nodeId = decodeIdSegment(String(params.node_id))
        nodeRequests.push(nodeId)
        return [200, nodeId === 'gen-2' ? answeredGeneration : makeNodeDetail({ id: nodeId })]
    },
}
const evaluationsMock = { [EVALUATIONS_URL]: () => [200, { results: [] }] }

const generation = makeEvent({
    id: 'gen-1',
    event: '$ai_generation',
    createdAt: '2026-09-01T10:15:02Z',
    properties: {
        $ai_trace_id: 'trace-1',
        $ai_parent_id: 'trace-1',
        $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
        $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
    },
})

function renderNewView(): ReturnType<typeof render> {
    initKeaTests()
    nodeRequests = []
    jest.mocked(performQuery).mockReset()
    jest.mocked(performQuery).mockResolvedValue({ results: [] })
    aiObservabilityTraceLogic.mount()
    router.actions.push(urls.aiObservabilityTrace('trace-1'))
    return render(<TraceScene />)
}

describe('TraceScene', () => {
    afterEach(cleanup)

    describe('the new view', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    [TRACE_URL]: () => [200, makeTraceResource({ defaultNodeId: 'gen-2' })],
                    ...nodeMock,
                    ...evaluationsMock,
                },
            })
        })

        it('opens on the default node without the legacy trace query', async () => {
            const { findAllByText, findByText } = renderNewView()

            expect((await findAllByText('answer-billing-question')).length).toBeGreaterThan(0)
            expect(await findByText('Two seats were added.')).toBeTruthy()
            expect(jest.mocked(performQuery).mock.calls.some(([query]) => query.kind === 'TraceQuery')).toBe(false)
        })

        it('starts reading a step when the pointer rests on its row', async () => {
            const { findByText } = renderNewView()
            const row = (await findByText('span-1')).closest('[data-attr="trace-view-tree-node"]')
            if (!row) {
                throw new Error('expected span-1 to render as a tree row')
            }
            nodeRequests = []

            fireEvent.mouseEnter(row)

            await waitFor(() => expect(nodeRequests).toContain('span-1'))
        })
    })

    describe('behind the flag gate', () => {
        beforeEach(() => {
            useMocks({ get: { [TRACE_URL]: () => [200, makeTraceResource()], ...nodeMock, ...evaluationsMock } })
        })

        async function renderTraceRoute(flagEnabled: boolean): Promise<ReturnType<typeof render>> {
            localStorage.clear()
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FLAG], { [FLAG]: flagEnabled })
            jest.mocked(performQuery).mockResolvedValue({ results: [makeTrace({ events: [generation] })] })
            aiObservabilityTraceLogic.mount()
            router.actions.push(urls.aiObservabilityTrace('trace-1'))
            // The old scene reads the project id while its modules load, so the import must follow initKeaTests.
            const { scene } = await import('../../../AIObservabilityTraceScene')
            const TraceRoute = scene.component
            return render(<TraceRoute />)
        }

        it('switches to the old view and back when the flag is on', async () => {
            const { findByText } = await renderTraceRoute(true)

            fireEvent.click(await findByText('Switch to the old view'))
            fireEvent.click(await findByText('Switch to the new view'))

            expect(await findByText('Switch to the old view')).toBeTruthy()
        })

        it('offers no switch on the old view when the flag is off', async () => {
            const { container, queryByText } = await renderTraceRoute(false)

            await waitFor(() => expect(container.querySelector('.AIObservabilityTraceScene__wrapper')).not.toBeNull())
            expect(queryByText('Switch to the new view')).toBeNull()
        })
    })
})
