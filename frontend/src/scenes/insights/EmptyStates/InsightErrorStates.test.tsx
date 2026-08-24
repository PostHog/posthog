import { cleanup, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DashboardPlacement } from '~/types'

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
        const { container } = render(
            <InsightValidationError
                detail="Funnels require at least two steps."
                validationErrorCode="funnels_require_at_least_two_steps"
                query={{ kind: 'InsightVizNode', source: { kind: 'FunnelsQuery' } }}
            />
        )

        const shownCalls = captureSpy.mock.calls.filter((call) => call[0] === 'insight error message shown')
        expect(shownCalls).toHaveLength(1)
        expect(
            container.querySelector('[data-attr="insight-loading-too-long"]')?.classList.contains('text-danger')
        ).toBe(true)
        expect(screen.getByText('Open the query debugger and correct the query.')).toBeTruthy()
        expect(screen.getByText('Open in query debugger')).toBeTruthy()
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

    it('replaces generic invalid-query detail with a next step', () => {
        render(
            <InsightValidationError
                detail="The query is invalid."
                validationErrorCode="invalid_query"
                query={{ kind: 'InsightVizNode' }}
            />
        )

        expect(screen.getByText('Check the query for errors, then run it again.')).toBeTruthy()
        expect(screen.queryByText('The query is invalid.')).toBeNull()
        expect(screen.queryByText('Open the query debugger and correct the query.')).toBeNull()
        expect(screen.getByText('Open in query debugger')).toBeTruthy()
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
        { title: 'You do not have permission to run this query.', status: 403, raw: false },
        { title: 'The query was cancelled', status: undefined, raw: false },
        { title: 'This project has no events yet', status: undefined, raw: false },
    ])('classifies "$title" (status: $status) as raw=$raw', ({ title, status, raw }) => {
        expect(isRawServerErrorTitle(title, status)).toBe(raw)
    })

    it('does not expose raw ClickHouse errors', () => {
        const clickhouseError =
            'Code: 47. DB::Exception: Not found column mat_$survey_submission_id. Stack trace:\n0. DB::Exception::Exception()'
        const { container } = render(<InsightErrorState title={clickhouseError} onRetry={() => {}} />)

        const heading = container.querySelector('[data-attr="insight-loading-too-long"]')
        expect(heading?.textContent).toBe('There was a problem completing this query')
        expect(screen.queryByText(/DB::Exception/)).toBeNull()
        expect(screen.getByText(/Try again in a moment/)).toBeTruthy()
    })

    it.each([
        { status: 429, expectedCopy: 'Try again in 2 minutes.', retry: true },
        { status: 400, expectedCopy: 'Open the query debugger and correct the query.', retry: false },
        {
            status: 403,
            expectedCopy: 'Ask a project admin to grant you access to this insight.',
            retry: false,
            queryDebugger: false,
            bugReport: false,
        },
        { status: 503, expectedCopy: 'Try again in a moment.', retry: true, queryDebugger: false, bugReport: true },
    ])(
        'shows the correct action for HTTP $status errors',
        ({ status, expectedCopy, retry, queryDebugger = !retry, bugReport = false }) => {
            preflightLogic.actions.loadPreflightSuccess({ cloud: true } as any)

            const { container } = render(
                <InsightErrorState
                    title="The query failed."
                    titleStatus={status}
                    retryAfter={status === 429 ? 'in 2 minutes' : undefined}
                    query={{ kind: 'InsightVizNode' }}
                    onRetry={() => {}}
                />
            )

            expect(screen.getByText(expectedCopy)).toBeTruthy()
            expect(container.querySelector('[data-attr="insight-retry-button"]') !== null).toBe(retry)
            expect(screen.queryByText('Open in query debugger') !== null).toBe(queryDebugger)
            expect(screen.queryByText('If this persists, submit a bug report.') !== null).toBe(bugReport)
        }
    )

    it('uses user-facing copy for invalid query errors', () => {
        render(<InsightErrorState title="This query is invalid" titleStatus={400} query={{ kind: 'InsightVizNode' }} />)

        expect(screen.getByText("We couldn't run this query")).toBeTruthy()
        expect(screen.queryByText('This query is invalid')).toBeNull()
    })

    it.each([
        { status: 503, expectedTitle: "This query couldn't run right now" },
        { status: 500, expectedTitle: "PostHog couldn't complete this query" },
        { status: 418, expectedTitle: "We couldn't complete this query" },
    ])('uses clear copy for server error $status', ({ status, expectedTitle }) => {
        render(<InsightErrorState title="Internal server error" titleStatus={status} />)

        expect(screen.getByText(expectedTitle)).toBeTruthy()
        expect(screen.queryByText('Internal server error')).toBeNull()
    })

    it('preserves custom titles when the status is unknown', () => {
        render(<InsightErrorState title="Failed to load this data." />)

        expect(screen.getByText('Failed to load this data.')).toBeTruthy()
        expect(screen.queryByText("We couldn't complete this query")).toBeNull()
    })

    it('preserves JSX titles when the status is unknown', () => {
        render(<InsightErrorState title={<pre data-attr="error-details">Query failed</pre>} />)

        expect(screen.getByTestId('error-details')).toBeTruthy()
        expect(screen.queryByText("We couldn't complete this query")).toBeNull()
    })

    it.each([500, 503, 418])('shows an error icon instead of a mascot for server failure %s', (status) => {
        const { container } = render(<InsightErrorState title="Internal server error" titleStatus={status} />)

        expect(container.querySelector('svg.text-danger')).not.toBeNull()
        expect(container.querySelector('img')).toBeNull()
    })

    it('shows support without retry guidance for persistent errors', () => {
        preflightLogic.actions.loadPreflightSuccess({ cloud: true } as any)

        render(<InsightErrorState title="There is a persistent problem." supportOnly />)

        expect(screen.getByText('If this persists, submit a bug report.')).toBeTruthy()
        expect(screen.queryByText(/try again/i)).toBeNull()
    })

    it('hides support links and query IDs in exported errors', () => {
        render(
            <InsightErrorState
                title="There was a server problem."
                titleStatus={500}
                queryId="export-query-id"
                placement={DashboardPlacement.Export}
            />
        )

        expect(screen.queryByText('If this persists, submit a bug report.')).toBeNull()
        expect(screen.queryByText(/export-query-id/)).toBeNull()
    })

    it('keeps the next step visible when error details are excluded', () => {
        render(
            <InsightErrorState title="You do not have permission to run this query." titleStatus={403} excludeDetail />
        )

        expect(screen.getByText('Ask a project admin to grant you access to this insight.')).toBeTruthy()
    })
})
