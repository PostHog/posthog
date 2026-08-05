import type { Meta, StoryObj } from '@storybook/react'

import type { ChatMessage } from '../../types'
import { Message } from './Message'

// The bubbles a support teammate reads on a ticket. The interesting axis is who a message is for:
// a reply goes to the customer, a note stays inside — and a note left by our own agent is a
// different thing to read than one left by a colleague, so the two get their own stories.

const meta: Meta<typeof Message> = {
    title: 'Scenes-App/Support/Message',
    component: Message,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-07-25' },
}
export default meta

type Story = StoryObj<typeof Message>

function makeMessage(overrides: Partial<ChatMessage>): ChatMessage {
    return {
        id: '019f9582-93e7-77c1-8912-4f541d70cb13',
        content: 'Our warehouse resync reports success but the table comes back with fewer rows than the source.',
        authorType: 'customer',
        authorName: 'Jack Feltham',
        createdAt: '2026-07-25T09:12:00Z',
        ...overrides,
    }
}

function Thread({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="max-w-2xl">{children}</div>
}

export const FromCustomer: Story = {
    render: () => (
        <Thread>
            <Message message={makeMessage({})} isCustomer={true} />
        </Thread>
    ),
}

export const ReplyToCustomer: Story = {
    render: () => (
        <Thread>
            <Message
                message={makeMessage({
                    authorType: 'human',
                    authorName: 'Ada Okonjo',
                    content:
                        "Thanks for flagging — this is a bug on our side, and the pipeline team is on it. I'll come back to you once the table is whole again.",
                })}
                isCustomer={false}
                deliveryStatus="read"
            />
        </Thread>
    ),
}

export const PrivateNoteFromTeammate: Story = {
    render: () => (
        <Thread>
            <Message
                message={makeMessage({
                    authorType: 'human',
                    authorName: 'Ada Okonjo',
                    isPrivate: true,
                    content: 'Matches the truncation bug we fixed last month, so this may be a regression.',
                })}
                isCustomer={false}
            />
        </Thread>
    ),
}

export const PrivateNoteFromAssistant: Story = {
    render: () => (
        <Thread>
            <Message
                message={makeMessage({
                    authorType: 'AI',
                    authorName: 'PostHog Assistant',
                    isPrivate: true,
                    content:
                        'Three resyncs on the same config each finished as `Completed` with a different, incomplete row count. Resync discards the existing table first, so a complete table was replaced with a truncated one.',
                })}
                isCustomer={false}
            />
        </Thread>
    ),
}

// Both note styles together, which is the comparison worth looking at: the hue is the only thing
// saying which of these a person wrote.
export const BothNoteAuthors: Story = {
    render: () => (
        <Thread>
            <Message
                message={makeMessage({
                    authorType: 'AI',
                    authorName: 'PostHog Assistant',
                    isPrivate: true,
                    content:
                        'Three resyncs on the same config each finished as `Completed` with a different, incomplete row count.',
                })}
                isCustomer={false}
            />
            <Message
                message={makeMessage({
                    id: '019f954a-8ed0-7a18-a198-3ffed1a2def0',
                    authorType: 'human',
                    authorName: 'Ada Okonjo',
                    isPrivate: true,
                    createdAt: '2026-07-25T09:31:00Z',
                    content: 'Matches the truncation bug we fixed last month, so this may be a regression.',
                })}
                isCustomer={false}
            />
        </Thread>
    ),
}
