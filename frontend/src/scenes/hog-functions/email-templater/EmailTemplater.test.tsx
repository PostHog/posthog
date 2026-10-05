import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { NativeEmailIntegrationChoice } from './EmailTemplater'

let mockSenderRotationEnabled = false

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => ({ chooseSenders: jest.fn() }),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonInputSelect: () => <div data-attr="multiple-email-sender-select" />,
    LemonSelect: () => <div data-attr="single-email-sender-select" />,
}))

const OWN_SENDERS = [
    { id: 1, kind: 'email', display_name: 'Alice <alice@example.com>' },
    { id: 2, kind: 'email', display_name: 'Bob <bob@example.com>' },
]
const SANDBOX_SENDER = { id: 7, kind: 'email', display_name: 'Acme via PostHog <sandbox@example.com>' }

describe('NativeEmailIntegrationChoice', () => {
    afterEach(cleanup)

    const mockValues = (
        sandboxEmailSender: typeof SANDBOX_SENDER | null,
        overrides: Record<string, unknown> = {}
    ): void => {
        jest.mocked(useValues).mockReturnValue({
            senderIntegrationsLoading: false,
            logicProps: {},
            senderIntegrations: sandboxEmailSender ? [...OWN_SENDERS, sandboxEmailSender] : OWN_SENDERS,
            sandboxEmailSender,
            ...overrides,
        })
    }

    beforeEach(() => {
        mockValues(null)
    })

    it.each([
        [false, 'single-email-sender-select'],
        [true, 'multiple-email-sender-select'],
    ])('renders the expected sender picker when the rotation flag is %s', (flagEnabled, expectedPicker) => {
        mockSenderRotationEnabled = flagEnabled

        render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 1 }} onChange={jest.fn()} />)

        expect(screen.getByTestId(expectedPicker)).toBeInTheDocument()
        expect(screen.getByText('Custom sender')).toBeInTheDocument()
    })

    it('hides the custom sender controls and explains the recipient rule while the sandbox sender is selected', () => {
        mockSenderRotationEnabled = true
        mockValues(SANDBOX_SENDER)

        render(
            <NativeEmailIntegrationChoice
                label="From"
                value={{ integrationId: 7, email: 'custom@example.com', name: 'Custom' }}
                onChange={jest.fn()}
            />
        )

        expect(screen.queryByText('Custom sender')).not.toBeInTheDocument()
        expect(screen.queryByText('Custom address')).not.toBeInTheDocument()
        expect(screen.getByText('Delivers only to verified members of your organization.')).toBeInTheDocument()
    })

    it('shows the picker, not the empty state, while the sandbox sender is still being created', () => {
        mockSenderRotationEnabled = false
        mockValues(null, { senderIntegrations: [], senderIntegrationsLoading: true })

        render(<NativeEmailIntegrationChoice label="From" value={{}} onChange={jest.fn()} />)

        expect(screen.queryByText('No email senders configured yet')).not.toBeInTheDocument()
        expect(screen.getByTestId('single-email-sender-select')).toBeInTheDocument()
    })
})
