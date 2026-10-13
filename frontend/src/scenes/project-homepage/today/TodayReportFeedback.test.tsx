import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'
import { captureInboxReportFeedback } from 'products/signals/frontend/inbox/inboxAnalytics'

import { TodayReportFeedback } from './TodayReportFeedback'

jest.mock('products/signals/frontend/inbox/inboxAnalytics', () => ({
    ...jest.requireActual('products/signals/frontend/inbox/inboxAnalytics'),
    captureInboxReportFeedback: jest.fn(),
}))

describe('TodayReportFeedback', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/': makeReport({ id: 'report-today' }),
                '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                '/api/projects/:team_id/signals/reports/for_you/': { results: [], count: 0 },
                '/api/projects/:team_id/today/briefing/': [404, {}],
                '/api/projects/:team_id/today/reports/:id/page/': [404, {}],
            },
            post: {
                '/api/projects/:team_id/signals/reports/:id/feedback/': [200, { forwarded: false }],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REPORT_FEEDBACK_BANG], {
            [FEATURE_FLAGS.INBOX_REPORT_FEEDBACK_BANG]: true,
        })
        jest.mocked(captureInboxReportFeedback).mockClear()
        render(<TodayReportFeedback report={makeReport({ id: 'report-today' })} />)
    })

    afterEach(() => {
        cleanup()
    })

    it('pops the hog and records the rating from the Today surface on thumbs-up', async () => {
        await userEvent.click(screen.getByLabelText('This report was useful'))

        expect(document.querySelector('[data-attr="inbox-report-feedback-celebration"]')).toBeInTheDocument()
        expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1)
        expect(captureInboxReportFeedback).toHaveBeenCalledWith(
            expect.objectContaining({ sentiment: 'positive', surface: 'today' })
        )
    })
})
