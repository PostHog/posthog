import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailTemplater, NativeEmailIntegrationChoice } from './EmailTemplater'
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

const blankEmail = { design: null, html: '', text: '', subject: '', from: '', to: '' }

describe('email templater', () => {
    let unmountLogic: (() => void) | undefined

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

    afterEach(() => {
        cleanup()
        unmountLogic?.()
        unmountLogic = undefined
    })

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

    it.each([
        { name: 'the host opens another email', first: { emailKey: 'a' }, second: { emailKey: 'b' }, kept: false },
        { name: 'another editor takes its place', first: { key: 'a' }, second: { key: 'b' }, kept: false },
        {
            name: 'the same email remounts',
            first: { key: 'a', emailKey: 'same' },
            second: { key: 'b', emailKey: 'same' },
            kept: true,
        },
    ])('a converted document is kept ($kept) when $name', ({ first, second, kept }) => {
        initKeaTests()
        const logic = emailTemplaterLogic({ value: blankEmail, onChange: jest.fn(), type: 'native_email' })
        unmountLogic = logic.mount()
        const editor = ({ key, ...props }: { key?: string; emailKey?: string }): JSX.Element => (
            <EmailTemplater key={key} value={blankEmail} onChange={jest.fn()} type="native_email" {...props} />
        )
        const { rerender } = render(editor(first))
        const document = { version: 1, doc: { type: 'doc', content: [] } }
        act(() => logic.actions.setEmailConversion({ document, unsupported: [], notKept: [] }))

        rerender(editor(second))

        expect(logic.values.convertedEmailDocument).toEqual(kept ? document : null)
    })
})
