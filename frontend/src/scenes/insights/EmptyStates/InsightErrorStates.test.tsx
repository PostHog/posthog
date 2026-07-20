import { cleanup, render } from '@testing-library/react'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InsightErrorState, InsightValidationError } from './EmptyStates'

describe('insight error states', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        useMocks({})
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture')
        captureSpy.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it('reports "insight error message shown" when a validation error renders', () => {
        render(
            <InsightValidationError
                detail="Funnels require at least two steps."
                validationErrorCode="funnels_require_at_least_two_steps"
                query={{ kind: 'InsightVizNode', source: { kind: 'FunnelsQuery' } }}
            />
        )

        const shownCalls = captureSpy.mock.calls.filter((call) => call[0] === 'insight error message shown')
        expect(shownCalls).toHaveLength(1)
        // Exact match: raw error detail must stay out of telemetry
        expect(shownCalls[0][1]).toEqual({
            error_type: 'validation',
            code: 'funnels_require_at_least_two_steps',
            query_kind: 'FunnelsQuery',
        })
    })

    it('reports "insight error message shown" when a server error renders', () => {
        render(<InsightErrorState title="A server error occurred." queryId="test-query-id" />)

        const shownCalls = captureSpy.mock.calls.filter((call) => call[0] === 'insight error message shown')
        expect(shownCalls).toHaveLength(1)
        expect(shownCalls[0][1]).toEqual({
            error_type: 'server',
            query_kind: null,
            query_id: 'test-query-id',
        })
    })
})
