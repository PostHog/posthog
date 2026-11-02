import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { EmailSenderSummary } from './EmailSenderSummary'
import { NativeEmailIntegrationChoice } from './EmailTemplater'

let mockSenderRotationEnabled = false

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => ({ setEmailTemplateValue: jest.fn() }),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonInputSelect: ({ options }: { options: { key: string; label: string }[] }) => (
        <div data-attr="multiple-email-sender-select">
            {options.map((option) => (
                <span key={option.key}>{option.label}</span>
            ))}
        </div>
    ),
    LemonSelect: ({ options }: { options: { options: { value: number; label: string }[] }[] }) => (
        <div data-attr="single-email-sender-select">
            {options
                .flatMap((section) => section.options)
                .map((option) => (
                    <span key={option.value}>{option.label}</span>
                ))}
        </div>
    ),
}))

const ALICE = { id: 1, kind: 'email', display_name: 'Alice <alice@example.com>', config: { provider: 'ses' } }
const BOB = { id: 2, kind: 'email', display_name: 'Bob <bob@example.com>', config: { provider: 'ses' } }
const SANDBOX = {
    id: 3,
    kind: 'email',
    display_name: 'Acme via PostHog <hello@sandbox.example.com>',
    config: { provider: 'sandbox' },
}

describe('NativeEmailIntegrationChoice', () => {
    afterEach(cleanup)

    beforeEach(() => {
        jest.mocked(useValues).mockReturnValue({
            integrationsLoading: false,
            integrations: [ALICE, BOB, SANDBOX],
        })
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

    it.each([false, true])(
        'leaves the sandbox sender out of the picker when the rotation flag is %s',
        (flagEnabled) => {
            mockSenderRotationEnabled = flagEnabled

            render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 1 }} onChange={jest.fn()} />)

            expect(screen.getByText(ALICE.display_name)).toBeInTheDocument()
            expect(screen.queryByText(SANDBOX.display_name)).not.toBeInTheDocument()
        }
    )

    it('treats a project with only the sandbox sender as having no email sender', () => {
        jest.mocked(useValues).mockReturnValue({ integrationsLoading: false, integrations: [SANDBOX] })

        render(<NativeEmailIntegrationChoice label="From" value={{}} onChange={jest.fn()} />)

        expect(screen.getByText('No email senders configured yet')).toBeInTheDocument()
    })
})

describe('EmailSenderSummary', () => {
    afterEach(cleanup)

    it('does not show the sandbox sender as the sender of a transactional email', () => {
        // make_transactional rejects the sandbox sender, so the transactional editor must not offer it.
        jest.mocked(useValues).mockReturnValue({
            emailTemplate: { from: { integrationId: SANDBOX.id } },
            integrations: [ALICE, SANDBOX],
        })

        render(<EmailSenderSummary />)

        expect(screen.getByText('Choose who this email comes from')).toBeInTheDocument()
    })
})
