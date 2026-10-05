import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { NativeEmailIntegrationChoice, rotationSenders } from './EmailTemplater'

let mockSenderRotationEnabled = false

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
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

    const mockValues = (sandboxEmailSender: typeof SANDBOX_SENDER | null): void => {
        jest.mocked(useValues).mockReturnValue({
            integrationsLoading: false,
            logicProps: {},
            senderIntegrations: sandboxEmailSender ? [...OWN_SENDERS, sandboxEmailSender] : OWN_SENDERS,
            sandboxEmailSender,
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

    describe('rotationSenders', () => {
        it.each([
            {
                case: 'picking the sandbox sender drops the own senders',
                ids: [1, 2, 7],
                sandboxId: 7,
                selected: false,
                expected: [7],
            },
            {
                case: 'adding an own sender drops the sandbox sender',
                ids: [7, 1],
                sandboxId: 7,
                selected: true,
                expected: [1],
            },
            { case: 'own senders rotate as before', ids: [1, 2], sandboxId: 7, selected: false, expected: [1, 2] },
            {
                case: 'no sandbox sender on this surface',
                ids: [1, 7],
                sandboxId: undefined,
                selected: false,
                expected: [1, 7],
            },
        ])('$case', ({ ids, sandboxId, selected, expected }) => {
            expect(rotationSenders(ids, sandboxId, selected)).toEqual(expected)
        })
    })
})
