import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'
import type { ConversationMessage, ConversationTicket, SidePanelViewState } from 'products/conversations/frontend/types'

import { TodaySupportPanel } from './TodaySupportPanel'

// SCRATCH: local preview of the quill ticket UI, not for commit.

const TICKETS: ConversationTicket[] = [
    {
        id: 't-1',
        ticket_number: 1042,
        status: 'open',
        last_message: 'Thanks, that fixed the funnel. One more question about breakdowns though.',
        last_message_at: '2025-10-10T09:12:00Z',
        message_count: 4,
        created_at: '2025-10-09T15:00:00Z',
        unread_count: 2,
    },
    {
        id: 't-2',
        ticket_number: 1037,
        status: 'pending',
        last_message: 'We are looking into why the session replay is missing network requests.',
        last_message_at: '2025-10-08T11:30:00Z',
        message_count: 3,
        created_at: '2025-10-07T10:00:00Z',
        unread_count: 0,
    },
    {
        id: 't-3',
        ticket_number: 1001,
        status: 'resolved',
        last_message: 'Glad that worked. Closing this one out.',
        last_message_at: '2025-09-20T16:45:00Z',
        message_count: 6,
        created_at: '2025-09-18T08:00:00Z',
        unread_count: 0,
    },
]

const MESSAGES: ConversationMessage[] = [
    {
        id: 'm-1',
        content: 'My funnel shows 0% conversion on step 2 since yesterday. Nothing changed on our side.',
        author_type: 'customer',
        author_name: 'You',
        created_at: '2025-10-09T15:00:00Z',
        is_private: false,
    },
    {
        id: 'm-2',
        content:
            'Thanks for the report. Step 2 filters on `$current_url` with an exact match, and your URLs now carry a trailing slash. Try "contains" instead.',
        author_type: 'human',
        author_name: 'Support engineer',
        created_at: '2025-10-09T16:20:00Z',
        is_private: false,
    },
    {
        id: 'm-3',
        content: 'Thanks, that fixed the funnel.',
        author_type: 'customer',
        author_name: 'You',
        created_at: '2025-10-10T09:10:00Z',
        is_private: false,
    },
    {
        id: 'm-4',
        content: 'One more question about breakdowns though: can I break down by a cohort?',
        author_type: 'customer',
        author_name: 'You',
        created_at: '2025-10-10T09:12:00Z',
        is_private: false,
    },
]

const fakeConversations = {
    isAvailable: () => true,
    getTickets: async () => ({ results: TICKETS, has_more: false }),
    getMessages: async () => ({ messages: MESSAGES, has_more: false }),
    markAsRead: async () => undefined,
    sendMessage: async () => null,
    requestRestoreLink: async () => undefined,
}

function installFakeConversations(available: boolean): void {
    Object.defineProperty(posthog, 'conversations', {
        value: { ...fakeConversations, isAvailable: () => available },
        configurable: true,
        writable: true,
    })
}

type StoryArgs = { view: SidePanelViewState; unavailable?: boolean }

function Panel({ view }: Pick<StoryArgs, 'view'>): JSX.Element {
    const { setView, setCurrentTicket, setStatusFilter } = useActions(sidepanelTicketsLogic)
    useOnMountEffect(() => {
        if (view === 'ticket') {
            setCurrentTicket(TICKETS[0])
        } else if (view === 'list') {
            setStatusFilter('all')
        } else {
            setView(view)
        }
    })
    return (
        <div className="flex h-[900px] w-[420px] flex-col border border-border bg-surface-primary">
            <TodaySupportPanel />
        </div>
    )
}

const meta: Meta<StoryArgs> = {
    title: 'Scratch/Today support panel',
    parameters: {
        layout: 'padded',
        mockDate: '2025-10-10T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
    },
    render: (args) => <Panel {...args} />,
    decorators: [
        (Story, { args }) => {
            installFakeConversations(!args.unavailable)
            return <Story />
        },
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<StoryArgs>

export const TicketList: Story = { args: { view: 'list' } }
export const OpenTicket: Story = { args: { view: 'ticket' } }
export const NewTicket: Story = { args: { view: 'new' } }
export const RestoreTickets: Story = { args: { view: 'restore' } }
export const SupportChatUnavailable: Story = { args: { view: 'list', unavailable: true } }
