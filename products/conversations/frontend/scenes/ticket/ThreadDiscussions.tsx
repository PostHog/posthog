import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconChat } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture/ProfileBubbles'
import { pluralize } from 'lib/utils/strings'
import { getCommentAuthorName, getText } from 'scenes/comments/Comment'
import { CommentWithRepliesType, commentsLogic } from 'scenes/comments/commentsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, CommentType, SidePanelTab } from '~/types'

import type { TimelineExtra } from '../../components/Chat/MessageList'
import { TeamOnlyBadge } from '../../components/Chat/TeamOnlyBadge'

/**
 * When the discussion happened. The root's timestamp is what the reader means by "when this started",
 * but a deleted root leaves only replies, so fall back to the first of those rather than emitting an
 * undefined `at` — `MessageList` sorts on `new Date(at).getTime()`, and one NaN scrambles the whole
 * timeline, not just this entry.
 */
function anchorOf(thread: CommentWithRepliesType): string | undefined {
    return thread.comment?.created_at ?? thread.replies[0]?.created_at
}

/** How many Slack-only participants to name before summarising the rest. */
const MAX_NAMED_SLACK_PARTICIPANTS = 2

/**
 * Who is in the discussion.
 *
 * Split in two because the two kinds of participant can't be shown the same way: `ProfileBubbles` keys
 * on email, and someone replying from the mirrored Slack thread has no PostHog user at all. They can't
 * be a bubble — and they can't only be a tooltip either, or a discussion that moved entirely into Slack
 * (the case this whole surface exists for) would show no one. So they get named in the open instead.
 */
function participantsOf(thread: CommentWithRepliesType): {
    people: { email: string; name: string }[]
    slackNames: string[]
} {
    const all = [thread.comment, ...thread.replies].filter((comment): comment is CommentType => !!comment)

    const people: { email: string; name: string }[] = []
    const seenEmails = new Set<string>()
    const slackNames = new Set<string>()

    for (const comment of all) {
        const email = comment.created_by?.email
        if (email) {
            if (!seenEmails.has(email)) {
                seenEmails.add(email)
                people.push({ email, name: getCommentAuthorName(comment) })
            }
        } else {
            slackNames.add(getCommentAuthorName(comment))
        }
    }

    return { people, slackNames: [...slackNames] }
}

/** Slack participants as a short readable list: "Marius", "Marius, Ben", "Marius, Ben +3". */
function summariseSlackNames(names: string[]): string {
    const named = names.slice(0, MAX_NAMED_SLACK_PARTICIPANTS).join(', ')
    const rest = names.length - MAX_NAMED_SLACK_PARTICIPANTS
    return rest > 0 ? `${named} +${rest}` : named
}

/**
 * One team discussion, as an entry in the ticket thread.
 *
 * The ticket thread already carries two other things the customer can't see — a teammate's private
 * note (amber) and a Self-driving agent's report (AI purple) — so this has to read as a third, distinct
 * kind: a conversation among the team *about* this ticket, possibly happening in Slack right now. It
 * wears the accent colour and a chat mark to say that, and like the agent report it deliberately avoids
 * the message bubble so it never scans as something anybody said to the customer.
 *
 * The whole card is the click target (it opens the discussion side panel), so nothing inside it may be
 * interactive — hence the Slack channel is a tag here rather than the link it is in the side panel.
 */
export function ThreadDiscussionEntry({
    thread,
    onOpen,
}: {
    thread: CommentWithRepliesType
    onOpen: (threadId: string) => void
}): JSX.Element {
    const root = thread.comment
    const anchor = anchorOf(thread)
    const slackThread = root?.slack_thread
    const { people, slackNames } = participantsOf(thread)

    return (
        // Full width, unlike a message: messages are inset because they belong to one side of the
        // conversation, and this belongs to neither.
        <div className="mb-4">
            {/* Same header structure as a message and as an agent report, so the thread keeps one
                rhythm down the page: who on the left, the facts about this entry on the right. */}
            <div className="flex items-center justify-between w-full gap-2 mb-1">
                <div className="flex items-center gap-1.5 min-w-0">
                    <IconChat className="text-accent shrink-0" />
                    <span className="text-sm font-medium text-accent">Team discussion</span>
                    {root ? (
                        <span className="ph-no-capture text-xs text-muted-alt truncate">
                            Started by {getCommentAuthorName(root)}
                        </span>
                    ) : null}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    {/* "Internal", not the entry's name again: the left of the row already says what
                        this is, and the badge's job is only to promise the customer cannot see it.
                        Same split as an agent report, which reads "Self-driving" then "Internal". */}
                    <TeamOnlyBadge label="Internal" tone="discussion" />
                    {anchor ? (
                        <span className="text-xs text-muted-alt">
                            <TZLabel time={anchor} />
                        </span>
                    ) : null}
                </div>
            </div>
            {/* Not a bubble, and marked down its edge, so it never reads as something a person said to
                the customer. The edge is a pseudo-element so it can run the full height without fighting
                the border radius the way a left border does.

                A button rather than a styled div: this opens a panel instead of navigating, and a button
                is what gives keyboard users the entry the mouse already has. The hover pair (background
                and border) is the same one the ticket page's other clickable blocks use, so the card
                announces itself the way the rest of the page does. */}
            <button
                type="button"
                onClick={() => onOpen(thread.id)}
                className="relative block w-full cursor-pointer overflow-hidden rounded border border-primary bg-surface-primary text-left transition-colors hover:border-secondary hover:bg-surface-secondary py-2 pl-4 pr-3 after:content-[''] after:absolute after:inset-y-0 after:left-0 after:w-1 after:bg-accent"
                data-attr="ticket-thread-discussion"
            >
                {root ? (
                    <div className="ph-no-capture text-sm leading-snug line-clamp-2">{getText(root)}</div>
                ) : (
                    <div className="text-sm font-semibold italic text-secondary">Deleted comment</div>
                )}
                <div className="mt-1.5 flex items-center gap-2 text-xs text-muted">
                    <span className="shrink-0">{pluralize(thread.replies.length, 'reply', 'replies')}</span>
                    {people.length > 0 ? (
                        <ProfileBubbles
                            people={people}
                            tooltip={people.map((person) => person.name).join(', ')}
                            limit={4}
                        />
                    ) : null}
                    {slackNames.length > 0 ? (
                        <span className="ph-no-capture truncate">{summariseSlackNames(slackNames)}</span>
                    ) : null}
                    {slackThread ? (
                        // A tag, not a link: the card is one click target, and an anchor inside a button
                        // is invalid markup that swallows the card's own click.
                        <LemonTag size="small" type="muted" icon={<IconSlack />} className="ml-auto shrink-0">
                            {slackThread.channel_name ? `#${slackThread.channel_name}` : 'Synced to Slack'}
                        </LemonTag>
                    ) : null}
                </div>
            </button>
        </div>
    )
}

/** Discussions as thread entries, ordered by when each started. */
export function discussionTimelineExtras(
    threads: CommentWithRepliesType[],
    onOpen: (threadId: string) => void
): TimelineExtra[] {
    return threads.flatMap((thread) => {
        const at = anchorOf(thread)
        return at ? [{ at, element: <ThreadDiscussionEntry key={thread.id} thread={thread} onOpen={onOpen} /> }] : []
    })
}

/**
 * The ticket's own discussions, ready to drop into the thread.
 *
 * `commentsLogic` is keyed on scope+item_id, so this mounts the very same instance the discussion side
 * panel uses: a reply posted in the panel updates these cards with no wiring between the two. That also
 * means the props here must match what `sidePanelDiscussionLogic.commentsLogicProps` builds for a ticket
 * — if the ticket scene ever starts setting `activity_item_context`, it has to be added here too, or this
 * mount will quietly win and drop it.
 *
 * A hook rather than a `connect()` because there's no static-props path to it: `supportTicketSceneLogic`
 * is keyed by the ticket *number* from the URL, while a discussion is keyed by the ticket's UUID, which
 * only exists once the ticket has loaded.
 */
export function useDiscussionTimelineExtras(ticketId: string | undefined, enabled: boolean): TimelineExtra[] {
    // Mounted unconditionally to keep hook order stable across the scene's loading states; loadComments
    // already no-ops without an item_id, so an unloaded ticket costs nothing.
    const logic = commentsLogic({ scope: ActivityScope.TICKET, item_id: ticketId ?? '' })
    const { commentsWithReplies } = useValues(logic)
    const { maybeLoadComments, setSelectedComment } = useActions(logic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    useEffect(() => {
        if (enabled && ticketId) {
            maybeLoadComments()
        }
    }, [enabled, ticketId, maybeLoadComments])

    if (!enabled || !ticketId) {
        return []
    }

    return discussionTimelineExtras(commentsWithReplies, (threadId) => {
        openSidePanel(SidePanelTab.Discussion, threadId)
        // The panel selects from the URL option on change, so clicking the *same* card twice would
        // otherwise be a no-op — after the reader collapsed that thread, the card would stop working.
        setSelectedComment(threadId, true)
    })
}
