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
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonInputSelect: () => <div data-attr="multiple-email-sender-select" />,
    LemonSelect: () => <div data-attr="single-email-sender-select" />,
}))

describe('NativeEmailIntegrationChoice', () => {
    afterEach(cleanup)

    const ownSenders = [
        { id: 1, kind: 'email', display_name: 'Alice <alice@example.com>' },
        { id: 2, kind: 'email', display_name: 'Bob <bob@example.com>' },
    ]
    const sandboxSender = {
        id: 3,
        kind: 'email',
        display_name: 'Sandbox <hello@sandbox.example.com>',
        config: { provider: 'sandbox' },
    }

    beforeEach(() => {
        jest.mocked(useValues).mockReturnValue({
            integrationsLoading: false,
            integrations: [...ownSenders, sandboxSender],
            ownEmailIntegrations: ownSenders,
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

    it('offers no sender when the sandbox sender is the only one', () => {
        jest.mocked(useValues).mockReturnValue({
            integrationsLoading: false,
            integrations: [sandboxSender],
            ownEmailIntegrations: [],
        })

        render(<NativeEmailIntegrationChoice label="From" value={{}} onChange={jest.fn()} />)

        expect(screen.getByText('No email senders configured yet')).toBeInTheDocument()
    })
})
