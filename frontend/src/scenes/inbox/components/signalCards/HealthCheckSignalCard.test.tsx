import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { SignalNode } from 'scenes/debug/signals/types'

import { HealthCheckSignalCard } from './HealthCheckSignalCard'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

function makeSignal(payload: Record<string, unknown>, title: string, content: string): SignalNode {
    return {
        signal_id: 'signal-1',
        content,
        source_product: 'health_checks',
        source_type: 'health_issue',
        source_id: 'issue-1',
        weight: 0.5,
        timestamp: '2026-07-13T00:00:00Z',
        extra: {
            kind: 'sdk_outdated',
            severity: 'warning',
            issue_id: 'issue-1',
            title,
            summary: 'Migration required',
            link: '/health/sdk-health',
            url: 'https://app.posthog.com/health/sdk-health',
            payload,
        },
    }
}

describe('HealthCheckSignalCard', () => {
    afterEach(cleanup)

    it('renders the legacy Java signal as an artifact migration', () => {
        const signal = makeSignal(
            {
                sdk_name: 'posthog-java',
                current_version: 'Not reported',
                latest_version: '1.2.0',
                reason: 'Migrate to com.posthog:posthog-server.',
                migration_source: 'com.posthog.java:posthog',
                migration_target: 'com.posthog:posthog-server',
                usage: [],
            },
            'SDK migration recommended',
            'This SDK requires migration.'
        )

        const { container } = render(<HealthCheckSignalCard signal={signal} />)

        expect(screen.getByText('SDK migration recommended')).toBeInTheDocument()
        expect(screen.getByText('Outdated SDK')).toBeInTheDocument()
        expect(container).toHaveTextContent('com.posthog.java:posthog → com.posthog:posthog-server')
        expect(container).not.toHaveTextContent('Not reported →')
    })
})
