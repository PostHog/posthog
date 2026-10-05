import { cleanup, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { aiObservabilityTraceLogic } from '../../../aiObservabilityTraceLogic'
import { TraceScene } from '../TraceScene'
import { makeEvent, makeTrace, makeTraceResource } from './testFixtures'

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
})
