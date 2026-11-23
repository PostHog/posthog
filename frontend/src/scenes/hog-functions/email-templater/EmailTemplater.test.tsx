import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NativeEmailIntegrationChoice } from './EmailTemplater'
import { emailTemplaterLogic } from './emailTemplaterLogic'

let mockSenderRotationEnabled = false

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonInputSelect: () => <div data-attr="multiple-email-sender-select" />,
    LemonSelect: () => <div data-attr="single-email-sender-select" />,
}))

const sender = (id: number, email: string, config: Record<string, unknown> = {}): Record<string, unknown> => ({
    id,
    kind: 'email',
    display_name: email,
    icon_url: '',
    config: { email, domain: email.split('@')[1], verified: true, ...config },
    created_at: '2026-01-01T00:00:00Z',
    errors: '',
})

let mockSenders: Record<string, unknown>[] = []

function renderChoice(senders: Record<string, unknown>[]): void {
    mockSenders = senders
    initKeaTests()
    render(
        <BindLogic logic={emailTemplaterLogic} props={{ value: null, onChange: jest.fn(), type: 'native_email' }}>
            <NativeEmailIntegrationChoice label="From" value={{ integrationId: 1 }} onChange={jest.fn()} />
        </BindLogic>
    )
}

describe('NativeEmailIntegrationChoice', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [
                    200,
                    { count: mockSenders.length, next: null, results: mockSenders },
                ],
            },
        })
    })

    afterEach(cleanup)

    it.each([
        [false, 'single-email-sender-select'],
        [true, 'multiple-email-sender-select'],
    ])('renders the expected sender picker when the rotation flag is %s', async (flagEnabled, expectedPicker) => {
        mockSenderRotationEnabled = flagEnabled
        renderChoice([sender(1, 'alice@example.com'), sender(2, 'bob@example.com')])

        expect(await screen.findByTestId(expectedPicker)).toBeInTheDocument()
        expect(screen.getByText('Custom sender')).toBeInTheDocument()
    })

    it.each([false, true])(
        'warns that the selected sender stopped sending when the rotation flag is %s',
        async (flagEnabled) => {
            mockSenderRotationEnabled = flagEnabled
            renderChoice([
                sender(1, 'alice@example.com', { ses_sending_status: 'failed' }),
                sender(2, 'bob@example.org', { ses_sending_status: 'failed' }),
            ])

            expect(await screen.findByText(/^Sending stopped for example\.com:/)).toBeInTheDocument()
            expect(screen.queryByText(/example\.org/)).not.toBeInTheDocument()
        }
    )
})
