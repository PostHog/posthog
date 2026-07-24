import { fireEvent, render, screen } from '@testing-library/react'
import { KeyboardEvent, ReactNode } from 'react'

import { AlertNotificationDestinationEditor } from './AlertNotificationDestinationEditor'

jest.mock('@posthog/lemon-ui', () => ({
    LemonButton: ({ children }: { children: ReactNode }) => <button>{children}</button>,
    LemonBanner: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    LemonInput: ({
        onPressEnter,
        placeholder,
    }: {
        onPressEnter?: (event: KeyboardEvent<HTMLInputElement>) => void
        placeholder?: string
    }) => (
        <input
            placeholder={placeholder}
            onKeyDown={(event) => {
                if (event.key === 'Enter') {
                    onPressEnter?.(event)
                }
            }}
        />
    ),
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

    it('adds a valid URL on Enter without bubbling to the wizard', () => {
        const onAdd = jest.fn()
        const onWizardKeyDown = jest.fn()
        render(
            <div onKeyDown={onWizardKeyDown}>
                <AlertNotificationDestinationEditor
                    destinations={{ showExisting: false, existingLoading: false, existing: [], pending: [] }}
                    notificationType={{ options: [], value: 'webhook', onChange: jest.fn() }}
                    slack={{
                        notificationType: 'slack',
                        integrationsLoading: false,
                        integrationsFailed: false,
                        onRetryIntegrations: jest.fn(),
                        integrations: [],
                        channelValue: null,
                        onChannelValueChange: jest.fn(),
                    }}
                    url={{
                        input: { placeholder: 'https://example.com/webhook' },
                        value: 'https://example.com/destination',
                        onChange: jest.fn(),
                    }}
                    add={{ onClick: onAdd }}
                />
            </div>
        )

        const input = screen.getByPlaceholderText('https://example.com/webhook')
        fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
        expect(onAdd).not.toHaveBeenCalled()
        expect(onWizardKeyDown).not.toHaveBeenCalled()

        fireEvent.keyDown(input, { key: 'Enter' })

        expect(onAdd).toHaveBeenCalledTimes(1)
        expect(onWizardKeyDown).not.toHaveBeenCalled()
    })
})
