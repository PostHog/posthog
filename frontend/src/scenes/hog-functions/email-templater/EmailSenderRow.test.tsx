import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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
                    count: 1,
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
                    ],
                },
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('shows the sending stopped warning next to an address error', async () => {
        render(
            <BindLogic
                logic={emailTemplaterLogic}
                props={{
                    value: {
                        design: null,
                        html: '<div>Hello</div>',
                        text: 'Hello',
                        subject: 'Welcome',
                        from: { integrationId: 1, email: 'hello@example.org' },
                        to: '{{ person.properties.email }}',
                    },
                    onChange: jest.fn(),
                    type: 'native_email',
                }}
            >
                <EmailSenderRow />
            </BindLogic>
        )

        expect(await screen.findByText(/^Sending stopped for example\.com:.* Use an address/)).toBeInTheDocument()
    })
})
