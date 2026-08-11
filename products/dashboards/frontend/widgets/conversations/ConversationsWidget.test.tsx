import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { ConversationsWidget } from './ConversationsWidget'

describe('ConversationsWidget', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(posthog.capture).mockClear()
    })

    it('records when a ticket is opened from the widget', () => {
        render(
            <ConversationsWidget
                tileId={1}
                config={{ limit: 10 }}
                loading={false}
                result={{
                    results: [
                        {
                            id: 'ticket-1',
                            ticket_number: 123,
                            channel_source: 'email',
                            status: 'open',
                            priority: 'high',
                            assignee: null,
                            updated_at: '2026-08-11T12:00:00Z',
                            last_message_text: 'I need help with my dashboard.',
                            unread_team_count: 0,
                            email_subject: null,
                            requester_name: 'Jane Doe',
                            requester_email: 'jane@example.com',
                            sla_due_at: null,
                        },
                    ],
                }}
            />
        )

        fireEvent.click(screen.getByText('I need help with my dashboard.'))

        expect(posthog.capture).toHaveBeenCalledWith('support ticket opened from recent ticket list')
    })
})
