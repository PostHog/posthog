import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/feedback_state/': { sentiment: null, note: '' },
                '/api/projects/:team_id/signals/reports/:id/': makeReport({ id: 'report-today' }),
                '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                '/api/projects/:team_id/signals/reports/': { results: [], count: 0 },
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
        await waitFor(() => expect(screen.getByLabelText('This report was useful')).toBeEnabled())
    })

    afterEach(() => {
        cleanup()
    })

    it('pops the hog and records the rating from the Today surface on thumbs-up', async () => {
        await userEvent.click(screen.getByLabelText('This report was useful'))

        await waitFor(() =>
            expect(document.querySelector('[data-attr="inbox-report-feedback-celebration"]')).toBeInTheDocument()
        )
        await waitFor(() => expect(captureInboxReportFeedback).toHaveBeenCalledTimes(1))
        expect(captureInboxReportFeedback).toHaveBeenCalledWith(
            expect.objectContaining({ sentiment: 'positive', surface: 'today' })
        )
        await userEvent.click(screen.getByLabelText('This report was useful'))
        await waitFor(() =>
            expect(screen.getByLabelText('This report was useful')).toHaveAttribute('aria-pressed', 'false')
        )
    })

    it.each([200, 500])('disables note editing while a save is pending (HTTP %s)', async (status) => {
        await userEvent.click(screen.getByLabelText('This report was not useful'))
        const note = await screen.findByLabelText('Add a note about this report')
        let finishRequest!: () => void
        const responseReady = new Promise<void>((resolve) => {
            finishRequest = resolve
        })
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/:id/feedback/': async () => {
                    await responseReady
                    return [status, { forwarded: false }]
                },
            },
        })

        await userEvent.type(note, 'This report needs more detail{Enter}')
        await waitFor(() => expect(note).toBeDisabled())
        await userEvent.type(note, 'More text')
        expect(note).toHaveValue('This report needs more detail')
        finishRequest()

        if (status === 200) {
            expect(await screen.findByText('Note added: This report needs more detail')).toBeVisible()
        } else {
            await waitFor(() => expect(note).toBeEnabled())
            expect(note).toHaveValue('This report needs more detail')
        }
    })
})
