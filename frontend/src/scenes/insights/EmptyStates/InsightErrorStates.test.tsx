import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { InsightErrorState, InsightValidationError, isRawServerErrorTitle } from './EmptyStates'

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

    // The retry button only offers a side action (query debugger link) when it has a query. Without
    // one, `sideAction` must stay undefined so LemonButton doesn't render a stray empty side action.
    it.each([
        { name: 'without a query', query: undefined, expectsSideAction: false },
        {
            name: 'with a query',
            query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } },
            expectsSideAction: true,
        },
    ])('retry button side action $name', ({ query, expectsSideAction }) => {
        const { container } = render(<InsightErrorState onRetry={() => {}} query={query} />)

        expect(container.querySelector('[data-attr="insight-retry-button"]')).not.toBeNull()
        expect(container.querySelector('.LemonButtonWithSideAction') !== null).toBe(expectsSideAction)
    })

    // Long enough that a length heuristic would misclassify it as a raw server error
    const longCuratedMessage =
        'The estimated query size exceeds the limit for this project. Narrow the date range, remove ' +
        'high-cardinality breakdowns, or materialize the source view, then run the query again. See ' +
        'the query performance docs for the limits that apply.'

    it.each([
        { title: 'Code: 47. DB::Exception: Not found column mat_$survey_submission_id', status: undefined, raw: true },
        { title: 'Some error\nStack trace:\n0. DB::Exception::Exception()', status: undefined, raw: true },
        { title: 'Traceback (most recent call last): File "x.py"', status: undefined, raw: true },
        { title: '<QuerySomething object at 0x7f1234>', status: undefined, raw: true },
        { title: 'ValueError: bad input', status: undefined, raw: true },
        // Validation statuses carry user-facing copy, no matter how long
        { title: longCuratedMessage, status: 400, raw: false },
        { title: longCuratedMessage, status: undefined, raw: false },
        // ...but staff accounts receive raw traces on validation statuses too
        { title: 'Code: 241. DB::Exception: Memory limit exceeded. Stack trace:\n0.', status: 400, raw: true },
        // Non-validation statuses mean a server-side failure whose text is not meant for the heading
        { title: 'ClickHouse error while executing query.', status: 500, raw: true },
        { title: 'The query was cancelled', status: undefined, raw: false },
        { title: 'This project has no events yet', status: undefined, raw: false },
    ])('classifies "$title" (status: $status) as raw=$raw', ({ title, status, raw }) => {
        expect(isRawServerErrorTitle(title, status)).toBe(raw)
    })

    it('keeps a raw ClickHouse error out of the heading but reachable in the details panel', () => {
        const clickhouseError =
            'Code: 47. DB::Exception: Not found column mat_$survey_submission_id. Stack trace:\n0. DB::Exception::Exception()'
        const { container } = render(<InsightErrorState title={clickhouseError} onRetry={() => {}} />)

        const heading = container.querySelector('[data-attr="insight-loading-too-long"]')
        expect(heading?.textContent).toBe('There was a problem completing this query')
        // The raw error stays hidden until the user opens the details panel.
        expect(screen.queryByText(/DB::Exception/)).toBeNull()

        fireEvent.click(screen.getByText('Error details'))
        expect(screen.getByText(/DB::Exception/)).toBeTruthy()
    })

    it('shows support without retry guidance for persistent errors', () => {
        preflightLogic.actions.loadPreflightSuccess({ cloud: true } as any)

        render(<InsightErrorState title="There is a persistent problem." supportOnly />)

        expect(screen.getByText('If this persists, submit a bug report.')).toBeTruthy()
        expect(screen.queryByText(/try again/i)).toBeNull()
    })
})
