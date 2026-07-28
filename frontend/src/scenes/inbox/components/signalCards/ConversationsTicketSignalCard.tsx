import { IconChevronRight, IconComment, IconGithub, IconLetter } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { IconMicrosoftTeams, IconSlack } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTag, type LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type { ConversationsTicketSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Guard for Conversations ticket extras. Keys on the ticket number + channel source unique to this source. */
export function isConversationsTicketExtra(
    value: unknown
): value is Record<string, unknown> & ConversationsTicketSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'ticket_number' in extra && 'channel_source' in extra
}

/** Sentence-case a lower-case token, treating underscores as spaces (e.g. `on_hold` → "On hold"). */
function humanizeToken(value: string): string {
    const spaced = value.replace(/_/g, ' ')
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Map a Conversations ticket status to a tag colour. */
export function conversationsStatusTagType(s: string): LemonTagType {
    switch (s) {
        case 'resolved':
            return 'success'
        case 'new':
            return 'primary'
        case 'open':
        case 'pending':
        case 'on_hold':
        default:
            return 'default'
    }
}

/** Human label for a Conversations ticket status (Sentence-cased, underscores humanized). */
export function conversationsStatusLabel(s: string): string {
    return humanizeToken(s)
}

/** Map a Conversations ticket priority to a tag colour. */
export function conversationsPriorityTagType(p: string): LemonTagType {
    switch (p) {
        case 'high':
            return 'danger'
        case 'medium':
            return 'warning'
        case 'low':
        default:
            return 'default'
    }
}

/** Map a channel source to its brand icon, or null when unrecognized. */
export function conversationsChannelIcon(source: string): JSX.Element | null {
    switch (source) {
        case 'widget':
            return <IconComment />
        case 'email':
            return <IconLetter />
        case 'github':
            return <IconGithub />
        case 'slack':
            return <IconSlack />
        case 'teams':
            return <IconMicrosoftTeams />
        default:
            return null
    }
}

export function ConversationsTicketSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & ConversationsTicketSignalExtraApi
    const channelIcon = conversationsChannelIcon(extra.channel_source)

    return (
        <SignalCardShell signal={signal} label={extra.email_subject ?? undefined}>
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}
            <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary">
                <span className="font-mono font-medium">#{extra.ticket_number}</span>
                <LemonTag size="small" type={conversationsStatusTagType(extra.status)}>
                    {conversationsStatusLabel(extra.status)}
                </LemonTag>
                {extra.priority && (
                    <LemonTag size="small" type={conversationsPriorityTagType(extra.priority)}>
                        {humanizeToken(extra.priority)}
                    </LemonTag>
                )}
                <LemonTag size="small" type="muted">
                    <span className="flex items-center gap-1">
                        {channelIcon}
                        <span>
                            {extra.channel_source}
                            {extra.channel_detail && ` · ${humanizeToken(extra.channel_detail)}`}
                        </span>
                    </span>
                </LemonTag>
                <span>{humanFriendlyDetailedTime(extra.created_at)}</span>
            </div>
            <div className="flex items-center mt-2">
                <span className="flex-1" />
                <Link
                    to={urls.supportTicketDetail(extra.ticket_number)}
                    className="flex items-center gap-1 text-xs font-medium"
                >
                    Open ticket
                    <IconChevronRight />
                </Link>
            </div>
        </SignalCardShell>
    )
}

export const conversationsTicketSignalCardEntry: SignalCardEntry = {
    key: 'conversations',
    matches: (signal) => signal.source_product === 'conversations' && isConversationsTicketExtra(signal.extra),
    Component: ConversationsTicketSignalCard,
}
