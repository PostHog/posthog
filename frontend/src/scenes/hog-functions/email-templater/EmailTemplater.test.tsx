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

    beforeEach(() => {
        jest.mocked(useValues).mockReturnValue({
            integrationsLoading: false,
            integrations: [
                {
                    id: 1,
                    kind: 'email',
                    display_name: 'Alice <alice@example.com>',
                },
                {
                    id: 2,
                    kind: 'email',
                    display_name: 'Bob <bob@example.com>',
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

    it.each([false, true])(
        'warns that the selected sender stopped sending when the rotation flag is %s',
        (flagEnabled) => {
            mockSenderRotationEnabled = flagEnabled
            jest.mocked(useValues).mockReturnValue({
                integrationsLoading: false,
                integrations: [
                    {
                        id: 1,
                        kind: 'email',
                        display_name: 'Alice <alice@example.com>',
                        config: { domain: 'example.com', ses_sending_status: 'failed' },
                    },
                    {
                        id: 2,
                        kind: 'email',
                        display_name: 'Bob <bob@example.org>',
                        config: { domain: 'example.org', ses_sending_status: 'failed' },
                    },
                ],
            })

            render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 1 }} onChange={jest.fn()} />)

            expect(screen.getByText(/^Sending stopped for example\.com:/)).toBeInTheDocument()
            expect(screen.queryByText(/example\.org/)).not.toBeInTheDocument()
        }
    )
})
