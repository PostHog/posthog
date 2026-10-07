import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useValues } from 'kea'
import posthog from 'posthog-js'

import { NativeEmailIntegrationChoice } from './EmailTemplater'

let mockSenderRotationEnabled = false

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('products/workflows/frontend/Channels/EmailSetup/EmailSetupModal', () => ({
    EmailSetupModal: () => <div>Configure email sender</div>,
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonInputSelect: () => <div data-attr="multiple-email-sender-select" />,
    LemonSelect: () => <div data-attr="single-email-sender-select" />,
}))

describe('NativeEmailIntegrationChoice', () => {
    afterEach(cleanup)

    beforeEach(() => {
        jest.mocked(useValues).mockReturnValue({
            integrationsLoading: false,
            integrations: [
                {
                    id: 1,
                    kind: 'email',
                    display_name: 'Alice <alice@example.com>',
                    config: { email: 'alice@example.com', verified: true },
                },
                {
                    id: 2,
                    kind: 'email',
                    display_name: 'Bob <bob@example.com>',
                    config: { email: 'bob@example.dev', verified: false },
                },
            ],
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

    it.each([
        ['an unverified sender', 2, true],
        ['a verified sender', 1, false],
    ])('asks to verify the domain under the sender for %s', (_name, integrationId, expectsNotice) => {
        render(<NativeEmailIntegrationChoice label="From" value={{ integrationId }} onChange={jest.fn()} />)

        expect(!!screen.queryByText("bob@example.dev can't send until its domain is verified.")).toBe(expectsNotice)
        expect(screen.queryAllByText('Verify sender').length > 0).toBe(expectsNotice)
    })

    it('opens the sender setup and records where verification started', () => {
        const capture = jest.spyOn(posthog, 'capture').mockClear()
        render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 2 }} onChange={jest.fn()} />)

        fireEvent.click(screen.getAllByText('Verify sender')[0])

        expect(screen.getByText('Configure email sender')).toBeInTheDocument()
        expect(capture).toHaveBeenCalledWith('workflows verify sender clicked', { source: 'sender_field' })
    })
})
