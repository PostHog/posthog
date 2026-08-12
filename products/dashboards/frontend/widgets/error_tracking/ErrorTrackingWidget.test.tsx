import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen, cleanup } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import { ErrorTrackingWidget } from './ErrorTrackingWidget'

jest.mock('products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList', () => ({
    ErrorTrackingIssueList: ({ filterGroup }: { filterGroup?: unknown }): JSX.Element => (
        <div data-filter-group={JSON.stringify(filterGroup)}>Issue list</div>
    ),
}))

describe('ErrorTrackingWidget', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: true })
        exceptionIngestionLogic.mount()
        exceptionIngestionLogic.actions.loadExceptionIngestionStateSuccess(true)
    })

    const issue = {
        id: 'issue-1',
        name: 'TypeError',
        description: 'Something broke',
        function: 'load',
        source: 'app.js',
        library: 'web',
        status: 'active',
        assignee: null,
        first_seen: '2026-05-01T10:00:00.000Z',
        last_seen: '2026-05-26T08:00:00.000Z',
        aggregations: {
            occurrences: 1,
            sessions: 1,
            users: 1,
            volume_buckets: [],
        },
    }

    it('renders issue list when results exist', () => {
        render(
            <ErrorTrackingWidget
                tileId={1}
                config={{ limit: 10 }}
                loading={false}
                result={{ results: [issue], hasMore: false, limit: 10, totalCount: 1, totalCountCapped: false }}
            />
        )

        expect(screen.getByText('Issue list')).toBeInTheDocument()
        expect(screen.getByText('1 of 1 issue')).toBeInTheDocument()
    })

    it('forwards widget property filters to the issue list', () => {
        render(
            <ErrorTrackingWidget
                tileId={1}
                config={{
                    limit: 10,
                    widgetFilters: {
                        browser: {
                            filterId: 'browser',
                            propertyName: '$browser',
                            optionId: 'chrome',
                            value: 'Chrome',
                            operator: PropertyOperator.Exact,
                        },
                    },
                }}
                loading={false}
                result={{ results: [issue] }}
            />
        )

        expect(JSON.parse(screen.getByText('Issue list').dataset.filterGroup ?? '')).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$browser',
                            operator: PropertyOperator.Exact,
                            value: ['Chrome'],
                        },
                    ],
                },
            ],
        })
    })

    it('renders a celebratory empty state when there are no issues', () => {
        const { container } = render(
            <ErrorTrackingWidget tileId={1} config={{ limit: 10 }} loading={false} result={{ results: [] }} />
        )

        expect(container.querySelector('[data-attr="error-tracking-widget-empty-state"]')).toBeInTheDocument()
        expect(screen.getByText('All clear!')).toBeInTheDocument()
        expect(
            screen.getByText("No issues matched your filters. That's a good thing. Enjoy the quiet.")
        ).toBeInTheDocument()
        expect(screen.getByAltText('PostHog hedgehog')).toBeInTheDocument()
    })

    it('shows setup prompt when exception autocapture is disabled', async () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: false,
        })
        exceptionIngestionLogic.actions.loadExceptionIngestionStateSuccess(false)

        render(<ErrorTrackingWidget tileId={1} config={{ limit: 10 }} loading={false} result={{ results: [issue] }} />)

        expect(await screen.findByText("You haven't captured any exceptions")).toBeInTheDocument()
        expect(screen.getByText('Enable exception autocapture').closest('button')).toBeInTheDocument()
        expect(screen.queryByText('Issue list')).not.toBeInTheDocument()
    })
})
