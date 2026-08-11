import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { CommentWithRepliesType } from 'scenes/comments/commentsLogic'

import type { CommentType } from '~/types'
import { ActivityScope } from '~/types'

import { ThreadDiscussionEntry, discussionTimelineExtras } from './ThreadDiscussions'

// TZLabel reads the current team's timezone off a mounted kea store; the behaviour under test is what
// the card says about the discussion, not how the timestamp is localised.
jest.mock('lib/components/TZLabel', () => {
    const React = jest.requireActual<typeof import('react')>('react')
    return { TZLabel: ({ time }: { time: string }) => React.createElement('span', null, time) }
})

// Fully typed rather than cast, so a new required field on CommentType breaks this file instead of
// letting the fixture drift away from what the card is really handed.
function comment(overrides: Partial<CommentType> = {}): CommentType {
    return {
        id: 'comment-1',
        content: 'Is this the same bug as the flag eval regression?',
        rich_content: null,
        scope: ActivityScope.TICKET,
        item_id: 'ticket-1',
        item_context: null,
        created_at: '2026-01-01T00:00:00Z',
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

function thread(overrides: Partial<CommentWithRepliesType> = {}): CommentWithRepliesType {
    return { id: 'comment-1', comment: comment(), replies: [], ...overrides }
}

afterEach(cleanup)

describe('ThreadDiscussions', () => {
    it('marks the discussion team-only and names who started it', () => {
        render(<ThreadDiscussionEntry thread={thread()} onOpen={jest.fn()} />)

        expect(screen.getByText('Started by Luke')).toBeInTheDocument()
        expect(screen.getByText('Is this the same bug as the flag eval regression?')).toBeInTheDocument()
        // The row names the entry once on the left and promises team-only on the right. Saying
        // "Team discussion" in both places reads as a mistake next to an agent report, which
        // splits the same two jobs across two different words.
        expect(screen.getByText('Team discussion')).toBeInTheDocument()
        expect(screen.getByText('Internal')).toBeInTheDocument()
    })

    // Reactions are stripped upstream by commentsLogic's commentsWithReplies, so the card can trust
    // replies.length — this pins that it counts replies rather than re-deriving anything.
    it('counts replies', () => {
        render(
            <ThreadDiscussionEntry
                thread={thread({ replies: [comment({ id: 'r1' }), comment({ id: 'r2' })] })}
                onOpen={jest.fn()}
            />
        )

        expect(screen.getByText('2 replies')).toBeInTheDocument()
    })

    it('shows the Slack channel only once the discussion is mirrored', () => {
        const { rerender } = render(<ThreadDiscussionEntry thread={thread()} onOpen={jest.fn()} />)
        expect(screen.queryByText('#support-eng')).not.toBeInTheDocument()

        rerender(
            <ThreadDiscussionEntry
                thread={thread({
                    comment: comment({
                        slack_thread: {
                            channel_id: 'C123',
                            channel_name: 'support-eng',
                            url: 'https://slack.com/archives/C123/p1',
                        },
                    }),
                })}
                onOpen={jest.fn()}
            />
        )
        expect(screen.getByText('#support-eng')).toBeInTheDocument()
    })

    // A root can be deleted out from under its replies; the discussion still happened.
    it('degrades to a deleted-comment body when the root is gone', () => {
        render(
            <ThreadDiscussionEntry
                thread={thread({ comment: undefined, replies: [comment({ id: 'r1' })] })}
                onOpen={jest.fn()}
            />
        )

        expect(screen.getByText('Deleted comment')).toBeInTheDocument()
        expect(screen.getByText('1 reply')).toBeInTheDocument()
    })

    // Slack repliers have no PostHog user at all, so they can't be avatar bubbles. They must still be
    // named visibly - a discussion that moved entirely into Slack would otherwise show nobody.
    it('names Slack-authored participants in the open', () => {
        render(
            <ThreadDiscussionEntry
                thread={thread({
                    replies: [
                        comment({
                            id: 'r1',
                            created_by: null,
                            item_context: { from_slack: true, slack_author_name: 'Marius' },
                        }),
                    ],
                })}
                onOpen={jest.fn()}
            />
        )

        expect(screen.getByText('Marius')).toBeInTheDocument()
    })

    it('summarises a crowd of Slack participants', () => {
        render(
            <ThreadDiscussionEntry
                thread={thread({
                    replies: ['Marius', 'Ben', 'Tim', 'Kea'].map((name, index) =>
                        comment({
                            id: `r${index}`,
                            created_by: null,
                            item_context: { from_slack: true, slack_author_name: name },
                        })
                    ),
                })}
                onOpen={jest.fn()}
            />
        )

        expect(screen.getByText('Marius, Ben +2')).toBeInTheDocument()
    })

    it('opens the thread it represents', () => {
        const onOpen = jest.fn()
        render(<ThreadDiscussionEntry thread={thread()} onOpen={onOpen} />)

        fireEvent.click(screen.getByRole('button'))

        expect(onOpen).toHaveBeenCalledWith('comment-1')
    })

    describe('discussionTimelineExtras', () => {
        it('anchors each entry at the root comment', () => {
            expect(discussionTimelineExtras([thread()], jest.fn())[0].at).toBe('2026-01-01T00:00:00Z')
        })

        it('falls back to the first reply when the root was deleted', () => {
            const extras = discussionTimelineExtras(
                [
                    thread({
                        comment: undefined,
                        replies: [comment({ id: 'r1', created_at: '2026-01-02T00:00:00Z' })],
                    }),
                ],
                jest.fn()
            )

            expect(extras[0].at).toBe('2026-01-02T00:00:00Z')
        })

        // MessageList sorts on new Date(at).getTime(); one NaN reorders the whole timeline, not just
        // this entry, so a thread with no usable timestamp is dropped rather than emitted.
        it('drops a thread with no timestamp to anchor on', () => {
            expect(discussionTimelineExtras([{ id: 'x', comment: undefined, replies: [] }], jest.fn())).toEqual([])
        })
    })
})
