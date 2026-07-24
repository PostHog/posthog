import { render, screen } from '@testing-library/react'
import { ReactNode } from 'react'

import { AlertNotificationDestinationEditor } from './AlertNotificationDestinationEditor'

jest.mock('@posthog/lemon-ui', () => ({
    LemonButton: ({ children }: { children: ReactNode }) => <button>{children}</button>,
    LemonBanner: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    LemonInput: () => <input />,
    LemonSelect: () => <select />,
    LemonSkeleton: () => <div>Loading integrations</div>,
    LemonTag: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}))

jest.mock('lib/integrations/SlackIntegrationHelpers', () => ({
    SlackChannelPicker: () => <div>Slack channel picker</div>,
    SlackNotConfiguredBanner: () => <div>Slack is not yet configured for this project.</div>,
}))

describe('AlertNotificationDestinationEditor', () => {
    it('waits for integrations to load before showing Slack as not configured', () => {
        const props = {
            destinations: {
                showExisting: false,
                existingLoading: false,
                existing: [],
                pending: [],
            },
            notificationType: {
                options: [{ label: 'Slack', value: 'slack' }],
                value: 'slack',
                onChange: jest.fn(),
            },
            slack: {
                notificationType: 'slack',
                integrationsLoading: false,
                integrationsFailed: false,
                onRetryIntegrations: jest.fn(),
                channelValue: null,
                onChannelValueChange: jest.fn(),
            },
            add: { onClick: jest.fn() },
        }

        const { rerender } = render(<AlertNotificationDestinationEditor {...props} />)

        expect(screen.queryByText(/Slack is not yet configured/)).toBeNull()

        rerender(<AlertNotificationDestinationEditor {...props} slack={{ ...props.slack, integrations: [] }} />)

        expect(screen.getByText(/Slack is not yet configured/)).toBeTruthy()

        rerender(
            <AlertNotificationDestinationEditor
                {...props}
                slack={{ ...props.slack, integrations: [], integrationsFailed: true }}
            />
        )

        expect(screen.getByText("Couldn't load Slack workspaces.")).toBeTruthy()
        expect(screen.queryByText(/Slack is not yet configured/)).toBeNull()

        rerender(
            <AlertNotificationDestinationEditor
                {...props}
                slack={{ ...props.slack, integrationsLoading: true, integrationsFailed: true }}
            />
        )

        expect(screen.getByText('Loading integrations')).toBeTruthy()
        expect(screen.queryByText("Couldn't load Slack workspaces.")).toBeNull()
    })
})
