import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { webAnalyticsRecap } from 'products/web_analytics/frontend/generated/api'
import type { WebAnalyticsRecapResponseApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { webAnalyticsRecapLogic } from './webAnalyticsRecapLogic'

jest.mock('products/web_analytics/frontend/generated/api', () => ({
    webAnalyticsRecap: jest.fn(),
}))
jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

const mockRecap = webAnalyticsRecap as jest.Mock

function makeRecap(overrides: Partial<WebAnalyticsRecapResponseApi> = {}): WebAnalyticsRecapResponseApi {
    return {
        visitors: { current: 100, previous: 80, change: null },
        pageviews: { current: 200, previous: 150, change: null },
        sessions: { current: 90, previous: 70, change: null },
        bounce_rate: { current: 40, previous: 45, change: null },
        avg_session_duration: { current: '1m 20s', previous: '1m', change: null },
        top_pages: [],
        top_sources: [],
        goals: [],
        dashboard_url: 'http://localhost/project/1/web',
        persona: { id: 'rising_star', name: 'Rising Star', emoji: '🚀', blurb: 'Up!', color: '#6a5af0' },
        highlights: [],
        period_label: 'Last 7 days',
        period_start: '2025-01-22',
        period_end: '2025-01-29',
        project_name: 'Test',
        recap_url: 'http://localhost/project/1/web/recap?utm_source=web_analytics_recap',
        ...overrides,
    }
}

describe('webAnalyticsRecapLogic', () => {
    let logic: ReturnType<typeof webAnalyticsRecapLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        mockRecap.mockReset()
        jest.spyOn(posthog, 'capture').mockReturnValue(null as any)
        ;(copyToClipboard as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads the recap on mount and records opened + persona events', async () => {
        mockRecap.mockResolvedValue(makeRecap())
        logic = webAnalyticsRecapLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['recordOpened', 'loadRecapSuccess'])
            .toMatchValues({
                recap: expect.objectContaining({ persona: expect.objectContaining({ id: 'rising_star' }) }),
                recapLoading: false,
            })

        expect(mockRecap).toHaveBeenCalledWith(expect.any(String), { days: 7 })
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_opened',
            expect.objectContaining({
                period_start: null,
                period_end: null,
                persona: null,
                visitors: null,
            })
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_persona_assigned',
            expect.objectContaining({
                period_start: '2025-01-22',
                period_end: '2025-01-29',
                persona: 'rising_star',
                visitors: 100,
            })
        )
    })

    it('reuses the persisted recap on remount instead of refetching', async () => {
        mockRecap.mockResolvedValue(makeRecap())
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecapSuccess'])
        expect(mockRecap).toHaveBeenCalledTimes(1)
        logic.unmount()

        mockRecap.mockClear()
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['recordOpened'])

        expect(mockRecap).not.toHaveBeenCalled()
        expect(logic.values.recap).toMatchObject({ persona: { id: 'rising_star' } })
    })

    it('copies the recap link and records the share', async () => {
        mockRecap.mockResolvedValue(makeRecap())
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecapSuccess'])

        await expectLogic(logic, () => {
            logic.actions.copyRecapLink()
        }).toDispatchActions(['copyRecapLink', 'recordShared'])

        expect(copyToClipboard).toHaveBeenCalledWith(
            'http://localhost/project/1/web/recap?utm_source=web_analytics_recap',
            'recap link'
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_button_clicked',
            expect.objectContaining({
                button: 'copy_link',
                intent: 'share',
                destination: 'clipboard',
                persona: 'rising_star',
            })
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_shared',
            expect.objectContaining({ method: 'copy_link', period_start: '2025-01-22' })
        )
    })

    it('does not record a share when the clipboard write fails', async () => {
        mockRecap.mockResolvedValue(makeRecap())
        ;(copyToClipboard as jest.Mock).mockResolvedValueOnce(false)
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecapSuccess'])

        await expectLogic(logic, () => {
            logic.actions.copyRecapLink()
        }).toDispatchActions(['copyRecapLink', 'recordButtonClicked'])
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(copyToClipboard).toHaveBeenCalled()
        expect(posthog.capture).not.toHaveBeenCalledWith('web_analytics_recap_shared', expect.anything())
    })

    it('copies Slack-ready recap text and records the share', async () => {
        mockRecap.mockResolvedValue(makeRecap())
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecapSuccess'])

        await expectLogic(logic, () => {
            logic.actions.copyRecapForSlack()
        }).toDispatchActions(['copyRecapForSlack', 'recordShared'])

        expect(copyToClipboard).toHaveBeenCalledWith(expect.stringContaining('*Test website recap*'), 'Slack recap')
        expect(copyToClipboard).toHaveBeenCalledWith(expect.stringContaining('100 visitors'), 'Slack recap')
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_button_clicked',
            expect.objectContaining({
                button: 'copy_slack',
                intent: 'share',
                destination: 'clipboard',
            })
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_shared',
            expect.objectContaining({ method: 'copy_slack', persona: 'rising_star' })
        )
    })

    it('copies email-ready recap text and records the share', async () => {
        mockRecap.mockResolvedValue(makeRecap())
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecapSuccess'])

        await expectLogic(logic, () => {
            logic.actions.copyRecapForEmail()
        }).toDispatchActions(['copyRecapForEmail', 'recordShared'])

        expect(copyToClipboard).toHaveBeenCalledWith(
            expect.stringContaining('Subject: Test website recap:'),
            'email recap'
        )
        expect(copyToClipboard).toHaveBeenCalledWith(expect.stringContaining('View the full recap:'), 'email recap')
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_button_clicked',
            expect.objectContaining({
                button: 'copy_email',
                intent: 'share',
                destination: 'clipboard',
            })
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_shared',
            expect.objectContaining({ method: 'copy_email', persona: 'rising_star' })
        )
    })

    it('records PostHog AI CTA usage with recap context', async () => {
        mockRecap.mockResolvedValue(makeRecap())
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecapSuccess'])

        await expectLogic(logic, () => {
            logic.actions.recordCtaClicked('ask_posthog_ai')
        }).toDispatchActions(['recordCtaClicked', 'recordButtonClicked'])

        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_button_clicked',
            expect.objectContaining({
                button: 'ask_posthog_ai',
                intent: 'posthog_ai_usage',
                destination: 'posthog_ai_side_panel',
                period_end: '2025-01-29',
            })
        )
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_cta_clicked',
            expect.objectContaining({ cta: 'ask_posthog_ai', persona: 'rising_star' })
        )
    })

    it('routes Web analytics CTA clicks with recap attribution params', async () => {
        const pushSpy = jest.spyOn(router.actions, 'push').mockImplementation(() => {})
        mockRecap.mockResolvedValue(makeRecap())
        logic = webAnalyticsRecapLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecapSuccess'])

        await expectLogic(logic, () => {
            logic.actions.goToWebAnalytics('view_dashboard')
        }).toDispatchActions(['goToWebAnalytics', 'recordCtaClicked', 'recordButtonClicked'])

        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_recap_button_clicked',
            expect.objectContaining({
                button: 'view_dashboard',
                intent: 'web_analytics_view',
                destination: 'web_analytics_dashboard',
            })
        )
        expect(pushSpy).toHaveBeenCalledWith(urls.webAnalytics(), {
            utm_source: 'web_analytics_recap',
            utm_medium: 'recap_button',
            utm_campaign: 'weekly_recap',
            utm_content: 'view_dashboard',
        })
    })
})
