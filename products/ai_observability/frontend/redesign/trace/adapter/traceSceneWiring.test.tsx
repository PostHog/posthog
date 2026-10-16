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
import { makeEvent, makeTrace, makeTraceResource } from './testFixtures'

const FLAG = FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('../../../utils', () => ({
    ...jest.requireActual('../../../utils'),
    queryEvaluationRuns: jest.fn().mockResolvedValue([]),
}))

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

describe('TraceScene', () => {
    afterEach(cleanup)

    it('renders the loaded trace after showing the loading state', async () => {
        initKeaTests()
        type QueryResult = Awaited<ReturnType<typeof performQuery>>
        let resolveQuery: (value: QueryResult) => void = () => {}
        jest.mocked(performQuery).mockReturnValue(
            new Promise<QueryResult>((resolve) => {
                resolveQuery = resolve
            })
        )
        useMocks({ get: { '/api/projects/:team_id/ai_observability/traces/:id/': () => [200, makeTraceResource()] } })
        aiObservabilityTraceLogic.mount()
        router.actions.push(urls.aiObservabilityTrace('trace-1'))

        const { findAllByText, queryByText } = render(<TraceScene />)
        expect(queryByText('answer-billing-question')).toBeNull()

        resolveQuery({ results: [makeTrace({ events: [generation] })] })

        expect((await findAllByText('answer-billing-question')).length).toBeGreaterThan(0)
        await waitFor(() => expect(queryByText('Two seats were added.')).not.toBeNull())
    })

    describe('behind the flag gate', () => {
        beforeEach(() => {
            useMocks({
                get: { '/api/projects/:team_id/ai_observability/traces/:id/': () => [200, makeTraceResource()] },
            })
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
