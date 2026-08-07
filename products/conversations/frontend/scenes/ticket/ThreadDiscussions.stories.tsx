import type { Meta, StoryObj } from '@storybook/react'

import { CommentWithRepliesType } from 'scenes/comments/commentsLogic'

import type { CommentType } from '~/types'
import { ActivityScope } from '~/types'

import { ThreadDiscussionEntry } from './ThreadDiscussions'

// The thread entry a support teammate reads on a ticket to see that the team is talking about it —
// possibly in Slack. It sits alongside a private note (amber) and a Self-driving report (AI purple),
// so these stories exist mainly to check it still reads as a third, distinct kind of team-only entry.

const meta: Meta<typeof ThreadDiscussionEntry> = {
    title: 'Scenes-App/Support/ThreadDiscussionEntry',
    component: ThreadDiscussionEntry,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-07-25' },
}
export default meta

type Story = StoryObj<typeof ThreadDiscussionEntry>

// Fully typed rather than cast, so a new required field on CommentType breaks this file instead of
// letting the fixture drift away from what the card is really handed.
function makeComment(overrides: Partial<CommentType> = {}): CommentType {
    return {
        id: '019f9582-93e7-77c1-8912-4f541d70cb13',
        content: 'Is this the same flag-eval regression we shipped a fix for last week, or something new?',
        rich_content: null,
        scope: ActivityScope.TICKET,
        item_id: '019f9569-5d45-780a-8b63-ecd0dc71148e',
        item_context: null,
        created_at: '2026-07-25T09:12:00Z',
        created_by: {
            id: 1,
            uuid: 'user-1',
            distinct_id: 'user-1',
            first_name: 'Luke',
            email: 'luke@posthog.com',
        },
        version: 0,
        is_task: false,
        completed_at: null,
        completed_by: null,
        ...overrides,
    }
}

function slackReply(id: string, name: string): CommentType {
    return makeComment({
        id,
        created_by: null,
        item_context: { from_slack: true, slack_author_name: name },
    })
}

function makeThread(overrides: Partial<CommentWithRepliesType> = {}): CommentWithRepliesType {
    return { id: makeComment().id, comment: makeComment(), replies: [], ...overrides }
}

function Thread({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="max-w-2xl">{children}</div>
}

const noop = (): void => {}

export const JustStarted: Story = {
    render: () => (
        <Thread>
            <ThreadDiscussionEntry thread={makeThread()} onOpen={noop} />
        </Thread>
    ),
}

export const MirroredToSlack: Story = {
    render: () => (
        <Thread>
            <ThreadDiscussionEntry
                thread={makeThread({
                    comment: makeComment({
                        slack_thread: {
                            channel_id: 'C0123456789',
                            channel_name: 'support-eng',
                            url: 'https://posthog.slack.com/archives/C0123456789/p1753434720',
                        },
                    }),
                    replies: [
                        slackReply('reply-1', 'Marius'),
                        slackReply('reply-2', 'Ben'),
                        slackReply('reply-3', 'Tim'),
                    ],
                })}
                onOpen={noop}
            />
        </Thread>
    ),
}

// The case the whole surface exists for: the conversation moved into Slack, so nobody in it has a
// PostHog avatar. The participants still have to be visible.
export const EntirelyInSlack: Story = {
    render: () => (
        <Thread>
            <ThreadDiscussionEntry
                thread={makeThread({
                    comment: undefined,
                    replies: [
                        slackReply('reply-1', 'Marius'),
                        slackReply('reply-2', 'Ben'),
                        slackReply('reply-3', 'Tim'),
                        slackReply('reply-4', 'Kea'),
                    ],
                })}
                onOpen={noop}
            />
        </Thread>
    ),
}

export const SeveralDiscussions: Story = {
    render: () => (
        <Thread>
            <ThreadDiscussionEntry thread={makeThread()} onOpen={noop} />
            <ThreadDiscussionEntry
                thread={makeThread({
                    id: 'thread-2',
                    comment: makeComment({
                        id: 'thread-2',
                        content:
                            'Customer is on the enterprise plan and this is their second report this month — worth escalating?',
                        created_at: '2026-07-25T11:40:00Z',
                        created_by: {
                            id: 2,
                            uuid: 'user-2',
                            distinct_id: 'user-2',
                            first_name: 'Simon',
                            email: 'simon@posthog.com',
                        },
                        slack_thread: {
                            channel_id: 'C0000000001',
                            channel_name: 'support-escalations',
                            url: 'https://posthog.slack.com/archives/C0000000001/p1753443600',
                        },
                    }),
                    replies: [slackReply('reply-a', 'Marius')],
                })}
                onOpen={noop}
            />
        </Thread>
    ),
}
