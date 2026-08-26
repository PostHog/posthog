import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import type { WidgetAvailabilityConfig } from '../../widget_types/widgetAvailability'
import { WidgetRuntimeAvailabilityGuard } from './WidgetRuntimeAvailabilityGuard'

const availability: WidgetAvailabilityConfig = {
    requirement: 'exception_autocapture',
    unavailableTitle: "You haven't captured any exceptions",
    unavailableReason: 'Enable exception autocapture to get started.',
    setupActionLabel: 'Enable exception autocapture',
    docsHref: 'https://posthog.com/docs/error-tracking/installation',
}

const supportAvailability: WidgetAvailabilityConfig = {
    requirement: 'conversations_enabled',
    unavailableTitle: 'Keep customer conversations close to your product data',
    unavailableReason: 'Triage and respond to customer questions with the context you need to solve them.',
    setupActionLabel: 'Enable',
    docsHref: 'https://posthog.com/docs/support',
}

describe('WidgetRuntimeAvailabilityGuard', () => {
    afterEach(() => {
        cleanup()
    })

    it('renders children when the requirement is met', () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: true })

        render(
            <WidgetRuntimeAvailabilityGuard availability={availability}>
                <div>Widget body</div>
            </WidgetRuntimeAvailabilityGuard>
        )

        expect(screen.getByText('Widget body')).toBeInTheDocument()
        expect(screen.queryByText("You haven't captured any exceptions")).not.toBeInTheDocument()
    })

    it('renders setup UI when the requirement is unmet', () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: false })

        render(
            <WidgetRuntimeAvailabilityGuard availability={availability}>
                <div>Widget body</div>
            </WidgetRuntimeAvailabilityGuard>
        )

        expect(screen.getByText("You haven't captured any exceptions")).toBeInTheDocument()
        expect(screen.getByText('Enable exception autocapture').closest('a')).toBeInTheDocument()
        expect(screen.queryByText('Widget body')).not.toBeInTheDocument()
    })

    it('renders children when no availability config is provided', () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: false })

        render(
            <WidgetRuntimeAvailabilityGuard availability={undefined}>
                <div>Widget body</div>
            </WidgetRuntimeAvailabilityGuard>
        )

        expect(screen.getByText('Widget body')).toBeInTheDocument()
    })

    it('uses a custom unavailableContentFallback when provided', () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: false })

        render(
            <WidgetRuntimeAvailabilityGuard
                availability={availability}
                unavailableContentFallback={({ availability: config }) => (
                    <div>Custom setup for {config.requirement}</div>
                )}
            >
                <div>Widget body</div>
            </WidgetRuntimeAvailabilityGuard>
        )

        expect(screen.getByText('Custom setup for exception_autocapture')).toBeInTheDocument()
        expect(screen.queryByText('Widget body')).not.toBeInTheDocument()
    })

    it('tracks Support activation from the widget setup state', () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_enabled: false })
        jest.mocked(posthog.capture).mockClear()

        render(
            <WidgetRuntimeAvailabilityGuard
                availability={supportAvailability}
                widgetType="conversations_recent_tickets"
                widgetId="widget-1"
                dashboardId={1}
            >
                <div>Widget body</div>
            </WidgetRuntimeAvailabilityGuard>
        )

        fireEvent.click(screen.getByText('Enable'))

        expect(posthog.capture).toHaveBeenCalledWith('support activation started', {
            source: 'dashboard_widget',
            widget_type: 'conversations_recent_tickets',
            widget_id: 'widget-1',
            dashboard_id: 1,
        })
        expect(posthog.capture).toHaveBeenCalledWith('dashboard widget cross product activated', {
            widget_type: 'conversations_recent_tickets',
            widget_id: 'widget-1',
            dashboard_id: 1,
            cta: 'conversations_enabled',
        })
    })
})
