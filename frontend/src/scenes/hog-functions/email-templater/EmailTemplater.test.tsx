import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { EmailSenderSummary } from './EmailSenderSummary'
import { NativeEmailIntegrationChoice } from './EmailTemplater'

let mockSenderRotationEnabled = false
const mockChooseSenders = jest.fn()

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => ({ chooseSenders: mockChooseSenders, setEmailTemplateValue: jest.fn() }),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonInputSelect: ({
        options,
        value,
        onChange,
    }: {
        options: { key: string; label: string; value: number }[]
        value: number[]
        onChange: (value: number[]) => void
    }) => (
        <div data-attr="multiple-email-sender-select">
            {options.map((option) => (
                <button key={option.key} onClick={() => onChange([...value, option.value])}>
                    {option.label}
                </button>
            ))}
        </div>
    ),
    LemonSelect: ({
        options,
        onChange,
    }: {
        options: { options: { value: number; label: string }[] }[]
        onChange: (value: number) => void
    }) => (
        <div data-attr="single-email-sender-select">
            {options
                .flatMap((section) => section.options)
                .map((option) => (
                    <button key={option.value} onClick={() => onChange(option.value)}>
                        {option.label}
                    </button>
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
const SANDBOX_NOTE = 'Delivers only to verified members of your organization.'

function mockPicker(values: Record<string, unknown>): void {
    jest.mocked(useValues).mockReturnValue({
        integrationsLoading: false,
        integrations: [ALICE, BOB],
        ownEmailIntegrations: [ALICE, BOB],
        sandboxSender: null,
        isSandboxSenderSelected: false,
        logicProps: {},
        ...values,
    })
}

describe('email sender pickers', () => {
    afterEach(cleanup)

    beforeEach(() => {
        mockChooseSenders.mockClear()
    })

    it.each([
        [false, 'single-email-sender-select'],
        [true, 'multiple-email-sender-select'],
    ])('renders the expected sender picker when the rotation flag is %s', (flagEnabled, expectedPicker) => {
        mockSenderRotationEnabled = flagEnabled
        mockPicker({})

        render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 1 }} onChange={jest.fn()} />)

        expect(screen.getByTestId(expectedPicker)).toBeInTheDocument()
        expect(screen.getByText('Custom sender')).toBeInTheDocument()
        expect(screen.queryByText(SANDBOX_NOTE)).not.toBeInTheDocument()
    })

    it.each([false, true])(
        'offers the sandbox sender with its members-only note once selected, when the rotation flag is %s',
        (flagEnabled) => {
            mockSenderRotationEnabled = flagEnabled
            mockPicker({ sandboxSender: SANDBOX, isSandboxSenderSelected: true })

            render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 3 }} onChange={jest.fn()} />)

            expect(screen.getByText(SANDBOX.display_name)).toBeInTheDocument()
            expect(screen.getByText(SANDBOX_NOTE)).toBeInTheDocument()
            expect(screen.queryByText('Custom sender')).not.toBeInTheDocument()
        }
    )

    it.each([
        { listed: 'listed', rotation: false, sandboxSender: SANDBOX, pick: SANDBOX, expectedSenderIds: [3] },
        { listed: 'listed', rotation: true, sandboxSender: SANDBOX, pick: SANDBOX, expectedSenderIds: [1, 3] },
        { listed: 'not listed', rotation: false, sandboxSender: null, pick: BOB, expectedFrom: { integrationId: 2 } },
        {
            listed: 'not listed',
            rotation: true,
            sandboxSender: null,
            pick: BOB,
            expectedFrom: { integrationId: 1, integrationIds: [1, 2] },
        },
    ])(
        'routes a pick when the sandbox sender is $listed and rotation is $rotation',
        ({ rotation, sandboxSender, pick, expectedSenderIds, expectedFrom }) => {
            mockSenderRotationEnabled = rotation
            mockPicker({ sandboxSender })
            const onChange = jest.fn()

            render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 1 }} onChange={onChange} />)
            fireEvent.click(screen.getByText(pick.display_name))

            if (expectedSenderIds) {
                expect(mockChooseSenders).toHaveBeenCalledWith(expectedSenderIds)
                expect(onChange).not.toHaveBeenCalled()
            } else {
                expect(mockChooseSenders).not.toHaveBeenCalled()
                expect(onChange).toHaveBeenCalledWith(expect.objectContaining(expectedFrom))
            }
        }
    )

    it.each([
        { state: 'no own sender', integrations: [SANDBOX], showsConnect: true },
        { state: 'integrations not loaded yet', integrations: null, showsConnect: false },
    ])('shows the connect prompt for $state only when it should', ({ integrations, showsConnect }) => {
        mockPicker({ integrations, ownEmailIntegrations: [] })

        render(<NativeEmailIntegrationChoice label="From" value={{}} onChange={jest.fn()} />)

        expect(!!screen.queryByText('No email senders configured yet')).toBe(showsConnect)
    })

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
