import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

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
        expect(screen.getByRole('link', { name: 'Enable exception autocapture' })).toBeInTheDocument()
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
})
