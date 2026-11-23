import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailSenderRow } from './EmailSenderRow'
import { emailTemplaterLogic } from './emailTemplaterLogic'

describe('EmailSenderRow', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': {
                    count: 2,
                    next: null,
                    results: [
                        {
                            id: 1,
                            kind: 'email',
                            display_name: 'hello@example.com',
                            icon_url: '',
                            config: {
                                email: 'hello@example.com',
                                domain: 'example.com',
                                verified: true,
                                ses_sending_status: 'failed',
                            },
                            created_at: '2026-01-01T00:00:00Z',
                            errors: '',
                        },
                        {
                            id: 2,
                            kind: 'email',
                            display_name: 'hello@example.net',
                            icon_url: '',
                            config: { email: 'hello@example.net', domain: 'example.net', verified: true },
                            created_at: '2026-01-01T00:00:00Z',
                            errors: '',
                        },
                    ],
                },
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    function renderRow(from: Record<string, unknown>): HTMLElement {
        return render(
            <BindLogic
                logic={emailTemplaterLogic}
                props={{
                    value: {
                        design: null,
                        html: '<div>Hello</div>',
                        text: 'Hello',
                        subject: 'Welcome',
                        from,
                        to: '{{ person.properties.email }}',
                    },
                    onChange: jest.fn(),
                    type: 'native_email',
                }}
            >
                <EmailSenderRow />
            </BindLogic>
        ).container
    }

    it('shows the sending stopped warning next to an address error', async () => {
        renderRow({ integrationId: 1, email: 'hello@example.org' })

        expect(await screen.findByText(/^Sending stopped for example\.com:.* Use an address/)).toBeInTheDocument()
    })

    it('marks a stopped sender in the sender list', async () => {
        const container = renderRow({})

        await waitFor(() => expect(container.querySelector('[data-attr$="-sender-select"]')).not.toBeNull())
        fireEvent.click(container.querySelector('[data-attr$="-sender-select"]') as HTMLElement)

        const marks = await screen.findAllByText('Sending stopped')
        expect(marks).toHaveLength(1)
        expect(marks[0].parentElement).toHaveTextContent(/^hello@example\.comSending stopped$/)
    })
})
