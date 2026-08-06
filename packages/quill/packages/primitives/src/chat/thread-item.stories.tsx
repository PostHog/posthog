import type { Meta, StoryObj } from '@storybook/react'
import {
    BookmarkIcon,
    EllipsisVerticalIcon,
    ExternalLinkIcon,
    ForwardIcon,
    MessageSquareTextIcon,
    SmilePlusIcon,
} from 'lucide-react'
import * as React from 'react'

import { Avatar, AvatarFallback, AvatarGroup, AvatarImage } from '../avatar'
import { Badge } from '../badge'
import { TooltipProvider } from '../tooltip'
import {
    ThreadItem,
    ThreadItemAction,
    ThreadItemActions,
    ThreadItemAttachment,
    ThreadItemAttachmentContent,
    ThreadItemAttachmentImage,
    ThreadItemAttachmentTrigger,
    ThreadItemAuthor,
    ThreadItemBody,
    ThreadItemContent,
    ThreadItemGroup,
    ThreadItemGutter,
    ThreadItemHeader,
    ThreadItemLink,
    ThreadItemMention,
    ThreadItemReaction,
    ThreadItemReactionEmoji,
    ThreadItemReactions,
    ThreadItemReplies,
    ThreadItemRepliesLabel,
    ThreadItemRepliesMeta,
    ThreadItemTimestamp,
} from './thread-item'

const meta = {
    title: 'Primitives/Chat/ThreadItem',
    component: ThreadItem,
    tags: ['autodocs'],
    // ThreadItemActions ships its own TooltipProvider; this root one covers ThreadItemAction
    // used elsewhere (the add-reaction button in the reactions row).
    decorators: [
        (Story): React.ReactElement => (
            <TooltipProvider>
                <Story />
            </TooltipProvider>
        ),
    ],
} satisfies Meta<typeof ThreadItem>

export default meta
type Story = StoryObj<typeof meta>

const MEMBERS = [
    { src: 'https://i.pravatar.cc/96?img=12', name: 'Adam L', initials: 'AL' },
    { src: 'https://i.pravatar.cc/96?img=32', name: 'Grace Hopper', initials: 'GH' },
    { src: 'https://i.pravatar.cc/96?img=45', name: 'Alan Turing', initials: 'AT' },
]

function MemberAvatar({ index, href }: { index: number; href?: string }): React.ReactElement {
    const member = MEMBERS[index]
    return (
        <Avatar
            size="lg"
            render={
                href != null ? (
                    // eslint-disable-next-line react/forbid-elements
                    <a href={href} />
                ) : undefined
            }
        >
            <AvatarImage src={member.src} alt={member.name} />
            <AvatarFallback>{member.initials}</AvatarFallback>
        </Avatar>
    )
}

/** Minimal anatomy: gutter avatar, author + timestamp header, body. */
export const Basic = {
    render: () => (
        <div className="w-[480px]">
            <ThreadItem>
                <ThreadItemGutter>
                    <MemberAvatar index={0} />
                </ThreadItemGutter>
                <ThreadItemContent>
                    <ThreadItemHeader>
                        <ThreadItemAuthor>Adam L</ThreadItemAuthor>
                        <ThreadItemTimestamp dateTime="2026-07-01T16:23:00">4:23 PM</ThreadItemTimestamp>
                    </ThreadItemHeader>
                    <ThreadItemBody>Deploy is out — watching the dashboards for the next hour.</ThreadItemBody>
                </ThreadItemContent>
            </ThreadItem>
        </div>
    ),
} satisfies Story

/** The full anatomy: reactions, reply summary, and the hover/focus-revealed actions toolbar. */
export const Complete = {
    render: function CompleteStory(): React.ReactElement {
        const [reactions, setReactions] = React.useState({ victory: true, facepalm: false })
        return (
            <div className="w-[520px] py-4">
                <ThreadItem>
                    <ThreadItemGutter>
                        <MemberAvatar index={0} />
                    </ThreadItemGutter>
                    <ThreadItemContent>
                        <ThreadItemHeader>
                            <ThreadItemAuthor render={<button type="button" />}>Adam L</ThreadItemAuthor>
                            <ThreadItemTimestamp dateTime="2026-07-01T16:23:00">4:23 PM</ThreadItemTimestamp>
                        </ThreadItemHeader>
                        <ThreadItemBody>
                            PHEW: flight is actually at 7:15pm, I was correct originally. For some reason unbeknownst to
                            me, my wallet boarding pass says 5:50pm. Good to hang out with yall! Excited to build this.
                            Byeeeeee
                        </ThreadItemBody>
                        <ThreadItemReactions>
                            <ThreadItemReaction
                                pressed={reactions.victory}
                                onPressedChange={(pressed) => setReactions((r) => ({ ...r, victory: pressed }))}
                                aria-label={`Victory hand, ${reactions.victory ? 1 : 0} reactions`}
                            >
                                <ThreadItemReactionEmoji>✌️</ThreadItemReactionEmoji>
                                {reactions.victory ? 1 : 0}
                            </ThreadItemReaction>
                            <ThreadItemReaction
                                pressed={reactions.facepalm}
                                onPressedChange={(pressed) => setReactions((r) => ({ ...r, facepalm: pressed }))}
                                aria-label={`Facepalm, ${reactions.facepalm ? 2 : 1} reactions`}
                            >
                                <ThreadItemReactionEmoji>🤦‍♀️</ThreadItemReactionEmoji>
                                {reactions.facepalm ? 2 : 1}
                            </ThreadItemReaction>
                            <ThreadItemAction label="Add reaction" className="rounded-full">
                                <SmilePlusIcon />
                            </ThreadItemAction>
                        </ThreadItemReactions>
                        <ThreadItemReplies>
                            <AvatarGroup size="xs">
                                <Avatar>
                                    <AvatarImage src={MEMBERS[1].src} alt={MEMBERS[1].name} />
                                    <AvatarFallback>{MEMBERS[1].initials}</AvatarFallback>
                                </Avatar>
                            </AvatarGroup>
                            <ThreadItemRepliesLabel>1 reply</ThreadItemRepliesLabel>
                            <ThreadItemRepliesMeta>Today at 4:40 PM</ThreadItemRepliesMeta>
                        </ThreadItemReplies>
                    </ThreadItemContent>
                    <ThreadItemActions>
                        <ThreadItemAction label="Add reaction">
                            <SmilePlusIcon />
                        </ThreadItemAction>
                        <ThreadItemAction label="Reply in thread">
                            <MessageSquareTextIcon />
                        </ThreadItemAction>
                        <ThreadItemAction label="Forward message">
                            <ForwardIcon />
                        </ThreadItemAction>
                        <ThreadItemAction label="Save for later">
                            <BookmarkIcon />
                        </ThreadItemAction>
                        <ThreadItemAction label="More actions">
                            <EllipsisVerticalIcon />
                        </ThreadItemAction>
                    </ThreadItemActions>
                </ThreadItem>
            </div>
        )
    },
} satisfies Story

/**
 * A feed of items. Authors and gutter avatars render as profile links (the avatar image's alt
 * names the link; authors stay foreground-colored, underline on hover).
 * Continuation rows (same author) drop the header and avatar; a gutter timestamp appears when the
 * row is hovered or focused.
 */
export const Feed = {
    render: () => (
        <div className="w-[520px]">
            <ThreadItemGroup>
                <ThreadItem>
                    <ThreadItemGutter>
                        <MemberAvatar index={1} href="#profile-grace" />
                    </ThreadItemGutter>
                    <ThreadItemContent>
                        <ThreadItemHeader>
                            <ThreadItemAuthor
                                render={
                                    // eslint-disable-next-line react/forbid-elements
                                    <a href="#profile-grace" />
                                }
                            >
                                Grace Hopper
                            </ThreadItemAuthor>
                            <ThreadItemTimestamp dateTime="2026-07-01T16:10:00">4:10 PM</ThreadItemTimestamp>
                        </ThreadItemHeader>
                        <ThreadItemBody>Nanoseconds matter. Shipping the fix now.</ThreadItemBody>
                    </ThreadItemContent>
                    <ThreadItemActions>
                        <ThreadItemAction label="Add reaction">
                            <SmilePlusIcon />
                        </ThreadItemAction>
                        <ThreadItemAction label="More actions">
                            <EllipsisVerticalIcon />
                        </ThreadItemAction>
                    </ThreadItemActions>
                </ThreadItem>

                <ThreadItem>
                    <ThreadItemGutter>
                        <ThreadItemTimestamp dateTime="2026-07-01T16:11:00">4:11</ThreadItemTimestamp>
                    </ThreadItemGutter>
                    <ThreadItemContent>
                        <ThreadItemBody>
                            {/* Continuation rows hide the visible header — keep the author for screen readers. */}
                            <span className="sr-only">Grace Hopper: </span>
                            …and merged. CI is green.
                        </ThreadItemBody>
                        <ThreadItemReactions>
                            <ThreadItemReaction defaultPressed aria-label="Rocket, 3 reactions">
                                <ThreadItemReactionEmoji>🚀</ThreadItemReactionEmoji>3
                            </ThreadItemReaction>
                        </ThreadItemReactions>
                    </ThreadItemContent>
                    <ThreadItemActions>
                        <ThreadItemAction label="Add reaction">
                            <SmilePlusIcon />
                        </ThreadItemAction>
                        <ThreadItemAction label="More actions">
                            <EllipsisVerticalIcon />
                        </ThreadItemAction>
                    </ThreadItemActions>
                </ThreadItem>

                <ThreadItem>
                    <ThreadItemGutter>
                        <MemberAvatar index={2} href="#profile-alan" />
                    </ThreadItemGutter>
                    <ThreadItemContent>
                        <ThreadItemHeader>
                            <ThreadItemAuthor
                                render={
                                    // eslint-disable-next-line react/forbid-elements
                                    <a href="#profile-alan" />
                                }
                            >
                                Alan Turing
                            </ThreadItemAuthor>
                            <ThreadItemTimestamp dateTime="2026-07-01T16:15:00">4:15 PM</ThreadItemTimestamp>
                        </ThreadItemHeader>
                        <ThreadItemBody>Can we compute? Yes. Should we? Also yes.</ThreadItemBody>
                        <ThreadItemReplies>
                            <AvatarGroup size="xs">
                                <Avatar>
                                    <AvatarImage src={MEMBERS[0].src} alt={MEMBERS[0].name} />
                                    <AvatarFallback>{MEMBERS[0].initials}</AvatarFallback>
                                </Avatar>
                                <Avatar>
                                    <AvatarImage src={MEMBERS[1].src} alt={MEMBERS[1].name} />
                                    <AvatarFallback>{MEMBERS[1].initials}</AvatarFallback>
                                </Avatar>
                            </AvatarGroup>
                            <ThreadItemRepliesLabel>2 replies</ThreadItemRepliesLabel>
                            <ThreadItemRepliesMeta>Last reply today at 4:40 PM</ThreadItemRepliesMeta>
                        </ThreadItemReplies>
                    </ThreadItemContent>
                    <ThreadItemActions>
                        <ThreadItemAction label="Add reaction">
                            <SmilePlusIcon />
                        </ThreadItemAction>
                        <ThreadItemAction label="More actions">
                            <EllipsisVerticalIcon />
                        </ThreadItemAction>
                    </ThreadItemActions>
                </ThreadItem>
            </ThreadItemGroup>
        </div>
    ),
} satisfies Story

/**
 * Rich content: a badge next to the author (header is an open flex row — drop any meta in),
 * an @mention and a link in the body, and a collapsible image attachment.
 */
export const RichContent = {
    render: () => (
        <div className="w-[560px]">
            <ThreadItem>
                <ThreadItemGutter>
                    <MemberAvatar index={1} />
                </ThreadItemGutter>
                <ThreadItemContent>
                    <ThreadItemHeader>
                        <ThreadItemAuthor render={<button type="button" />}>Raquel Smith</ThreadItemAuthor>
                        <Badge>VIP</Badge>
                        <ThreadItemTimestamp dateTime="2026-07-01T16:56:00">4:56 PM</ThreadItemTimestamp>
                    </ThreadItemHeader>
                    <ThreadItemBody>
                        <ThreadItemMention render={<button type="button" />}>@Adam L</ThreadItemMention> why this
                        checkbox? Context in <ThreadItemLink href="#docs">the scaffold docs</ThreadItemLink>.
                    </ThreadItemBody>
                    <ThreadItemAttachment>
                        <ThreadItemAttachmentTrigger>image.png</ThreadItemAttachmentTrigger>
                        <ThreadItemAttachmentContent>
                            <ThreadItemAttachmentImage
                                src="https://picsum.photos/seed/quill-thread/640/280"
                                alt="Screenshot of the scaffold checkbox setting"
                                width={640}
                                height={280}
                            />
                        </ThreadItemAttachmentContent>
                    </ThreadItemAttachment>
                    <ThreadItemReplies>
                        <AvatarGroup size="xs">
                            <Avatar>
                                <AvatarImage src={MEMBERS[0].src} alt={MEMBERS[0].name} />
                                <AvatarFallback>{MEMBERS[0].initials}</AvatarFallback>
                            </Avatar>
                            <Avatar>
                                <AvatarImage src={MEMBERS[2].src} alt={MEMBERS[2].name} />
                                <AvatarFallback>{MEMBERS[2].initials}</AvatarFallback>
                            </Avatar>
                        </AvatarGroup>
                        <ThreadItemRepliesLabel>3 replies</ThreadItemRepliesLabel>
                        <ThreadItemRepliesMeta>Last reply 1 day ago</ThreadItemRepliesMeta>
                    </ThreadItemReplies>
                </ThreadItemContent>
                <ThreadItemActions>
                    <ThreadItemAction label="Add reaction">
                        <SmilePlusIcon />
                    </ThreadItemAction>
                    <ThreadItemAction label="Reply in thread">
                        <MessageSquareTextIcon />
                    </ThreadItemAction>
                    <ThreadItemAction label="Forward message">
                        <ForwardIcon />
                    </ThreadItemAction>
                    <ThreadItemAction label="Save for later">
                        <BookmarkIcon />
                    </ThreadItemAction>
                    <ThreadItemAction
                        label="Open thread in new tab"
                        render={
                            // eslint-disable-next-line react/forbid-elements
                            <a href="#thread" target="_blank" rel="noreferrer" />
                        }
                    >
                        <ExternalLinkIcon />
                    </ThreadItemAction>
                </ThreadItemActions>
            </ThreadItem>
        </div>
    ),
} satisfies Story

/** Reply summary rendered as a link instead of a button. */
export const RepliesAsLink = {
    render: () => (
        <div className="w-[480px]">
            <ThreadItem>
                <ThreadItemGutter>
                    <MemberAvatar index={0} />
                </ThreadItemGutter>
                <ThreadItemContent>
                    <ThreadItemHeader>
                        <ThreadItemAuthor>Adam L</ThreadItemAuthor>
                        <ThreadItemTimestamp dateTime="2026-07-01T16:23:00">4:23 PM</ThreadItemTimestamp>
                    </ThreadItemHeader>
                    <ThreadItemBody>Thread summary can navigate instead of toggling a panel.</ThreadItemBody>
                    <ThreadItemReplies
                        render={
                            // eslint-disable-next-line react/forbid-elements
                            <a href="#thread" />
                        }
                    >
                        <AvatarGroup size="xs">
                            <Avatar>
                                <AvatarImage src={MEMBERS[2].src} alt={MEMBERS[2].name} />
                                <AvatarFallback>{MEMBERS[2].initials}</AvatarFallback>
                            </Avatar>
                        </AvatarGroup>
                        <ThreadItemRepliesLabel>1 reply</ThreadItemRepliesLabel>
                        <ThreadItemRepliesMeta>Today at 4:40 PM</ThreadItemRepliesMeta>
                    </ThreadItemReplies>
                </ThreadItemContent>
            </ThreadItem>
        </div>
    ),
} satisfies Story
