import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { ConversationsWidget, ConversationsWidgetTopHeading } from './ConversationsWidget'
import { conversationsWidgetSavedViewsLogic } from './conversationsWidgetSavedViewsLogic'

describe('ConversationsWidget', () => {
    beforeEach(() => {
        initKeaTests(true, MOCK_DEFAULT_TEAM)
        teamLogic.mount()
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
                            assignee: {
                                user: { id: 1, name: 'Test user' },
                                role: null,
                            },
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

        expect(posthog.capture).toHaveBeenCalledWith('dashboard widget open support ticket clicked', {
            widget_type: 'conversations_recent_tickets',
            tile_id: 1,
            ticket_id: 'ticket-1',
        })
    })

    it('shows the saved view name in the card top heading', () => {
        const savedViewsLogic = conversationsWidgetSavedViewsLogic({ projectId: teamLogic.values.currentProjectId })
        savedViewsLogic.mount()
        savedViewsLogic.actions.loadSavedViewsSuccess([
            {
                id: 'view-1',
                short_id: 'needs-reply',
                name: 'Needs a reply',
                created_at: '2026-08-11T12:00:00Z',
                created_by: {
                    id: 1,
                    uuid: 'user-1',
                    email: 'creator@example.com',
                    hedgehog_config: null,
                },
            },
        ])

        render(
            <ConversationsWidgetTopHeading
                config={{ savedViewId: 'needs-reply' }}
                widgetTypeLabel="Support"
                showWidgetType
                dateText={null}
            />
        )

        expect(screen.getByText('Support')).toBeInTheDocument()
        expect(screen.getByText('Needs a reply')).toBeInTheDocument()
    })
})
