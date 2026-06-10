import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen, cleanup } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import { ErrorTrackingWidget } from './ErrorTrackingWidget'

jest.mock('products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList', () => ({
    ErrorTrackingIssueList: (): JSX.Element => <div>Issue list</div>,
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

    it('shows capped total in footer when more issues exist than the count cap', () => {
        render(
            <ErrorTrackingWidget
                tileId={1}
                config={{ limit: 1, status: 'active', dateRange: { date_from: '-7d' } }}
                loading={false}
                result={{ results: [issue], hasMore: true, limit: 1, totalCount: 25, totalCountCapped: true }}
            />
        )

        expect(screen.getByText('1 of 25+ issues')).toBeInTheDocument()
    })

    it('shows lower-bound footer when hasMore and total count was not fetched', () => {
        render(
            <ErrorTrackingWidget
                tileId={1}
                config={{ limit: 1 }}
                loading={false}
                result={{ results: [issue], hasMore: true, limit: 1 }}
            />
        )

        expect(screen.getByText('1+ issue')).toBeInTheDocument()
    })

    it('shows exact total in footer when hasMore and total is known', () => {
        render(
            <ErrorTrackingWidget
                tileId={1}
                config={{ limit: 1 }}
                loading={false}
                result={{ results: [issue], hasMore: true, limit: 1, totalCount: 4, totalCountCapped: false }}
            />
        )

        expect(screen.getByText('1 of 4 issues')).toBeInTheDocument()
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
        expect(screen.getByRole('button', { name: 'Enable exception autocapture' })).toBeInTheDocument()
        expect(screen.queryByText('Issue list')).not.toBeInTheDocument()
    })
})
