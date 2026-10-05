import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { NativeEmailIntegrationChoice, selectSenders } from './EmailTemplater'

let mockSenderRotationEnabled = false

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => ({ setEmailTemplateValue: jest.fn(), hideAdvancedField: jest.fn() }),
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
            emailIntegrationsLoading: false,
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
        mockValues(null, { senderIntegrations: [], emailIntegrationsLoading: true })

        render(<NativeEmailIntegrationChoice label="From" value={{}} onChange={jest.fn()} />)

        expect(screen.queryByText('No email senders configured yet')).not.toBeInTheDocument()
        expect(screen.getByTestId('single-email-sender-select')).toBeInTheDocument()
    })

    describe('selectSenders', () => {
        const current = { integrationId: 1, email: 'custom@example.com', name: 'Custom' }

        it.each([
            {
                case: 'picking the sandbox sender keeps only it and drops the custom sender values',
                ids: [1, 2, 7],
                sandboxId: 7,
                expected: { integrationId: 7, integrationIds: undefined, email: undefined, name: undefined },
            },
            {
                case: 'adding an own sender while the sandbox sender is selected drops the sandbox sender',
                value: { integrationId: 7 },
                ids: [7, 1],
                sandboxId: 7,
                expected: { integrationId: 1, integrationIds: undefined },
            },
            {
                case: 'own senders rotate and keep the custom sender values',
                ids: [1, 2],
                sandboxId: 7,
                expected: { integrationId: 1, integrationIds: [1, 2], email: 'custom@example.com', name: 'Custom' },
            },
            {
                case: 'picking the sandbox sender over a full rotation still works',
                ids: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 7],
                sandboxId: 7,
                expected: { integrationId: 7, integrationIds: undefined },
            },
            {
                case: 'a surface without the sandbox sender treats its id like any other',
                ids: [1, 7],
                sandboxId: undefined,
                expected: { integrationId: 1, integrationIds: [1, 7] },
            },
            {
                case: 'more senders than the limit are refused',
                ids: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12],
                sandboxId: 7,
                expected: null,
            },
        ])('$case', ({ value = current, ids, sandboxId, expected }) => {
            expect(selectSenders(value, ids, sandboxId)).toEqual(
                expected === null ? null : expect.objectContaining(expected)
            )
        })
    })
})
