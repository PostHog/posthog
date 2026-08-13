import { JSONContent } from '@tiptap/core'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { toParams } from 'lib/utils/url'
import { urls } from 'scenes/urls'

import api, { CountedPaginatedResponse } from '~/lib/api'
import { groupsModel } from '~/models/groupsModel'
import type { CommentType, Group } from '~/types'

import { type ChatMessage, type Ticket, priorityOptions, statusOptionsWithoutAll } from '../../types'
import { serializeToMarkdown } from '../Editor'

const AUTHOR_TYPE_LABELS: Record<ChatMessage['authorType'], string> = {
    customer: 'Customer',
    human: 'Support',
    AI: 'AI agent',
}

/** Resolve a ticket comment's display identity. Used by both the chat view and the copied transcript. */
export function commentToChatMessage(message: CommentType, ticket: Ticket | null): ChatMessage {
    const authorType = message.item_context?.author_type || 'customer'
    let displayName = 'Anonymous user'
    if (message.created_by) {
        displayName =
            [message.created_by.first_name, message.created_by.last_name].filter(Boolean).join(' ') ||
            message.created_by.email ||
            'Support'
    } else if (authorType === 'AI') {
        displayName = 'PostHog Assistant'
    } else {
        // Per-message author identity (e.g. Zendesk import stores each comment's own
        // author) takes precedence over the ticket-level requester, so a reply from a
        // second requester or an agent shows the real name instead of the ticket owner.
        const messageAuthorName =
            message.item_context?.author_name ||
            message.item_context?.author_email ||
            message.item_context?.slack_author_name ||
            message.item_context?.teams_author_name ||
            message.item_context?.teams_author_email ||
            message.item_context?.email_from_name
        if (messageAuthorName) {
            displayName = messageAuthorName
        } else if (authorType === 'customer') {
            displayName =
                ticket?.person?.properties?.name ||
                ticket?.person?.properties?.email ||
                ticket?.anonymous_traits?.name ||
                ticket?.anonymous_traits?.email ||
                'Anonymous user'
        } else {
            // Staff message with no resolvable author (e.g. deleted ex-agent).
            displayName = 'Support'
        }
    }

    return {
        id: message.id,
        content: message.content || '',
        richContent: message.rich_content,
        authorType: authorType === 'support' ? 'human' : authorType,
        authorName: displayName,
        createdBy: message.created_by,
        createdAt: message.created_at,
        isPrivate: message.item_context?.is_private || false,
        version: message.version,
        emailDeliveryStatus: message.item_context?.email_delivery_status,
        fromZendesk: message.item_context?.from_zendesk === true,
    }
}

// UTC keeps timestamps unambiguous when the transcript is shared across timezones
function formatTimestamp(isoString: string): string {
    return dayjs(isoString).utc().format('YYYY-MM-DD HH:mm [UTC]')
}

// Header fields are single-line by construction; an author name or subject containing
// line breaks could otherwise fabricate transcript structure (fake headings or rules)
function singleLine(text: string): string {
    return text.replace(/\s+/g, ' ').trim()
}

function messageBody(message: ChatMessage): string {
    // content is the canonical markdown, written at send/import time; richContent is
    // the rich editor source it was serialized from, kept as a fallback
    const content = message.content?.trim()
    if (content) {
        return content
    }
    return message.richContent ? serializeToMarkdown(message.richContent as JSONContent) : ''
}

// Roles live in the Participants section of the header, not in every message heading
function messageSection(message: ChatMessage): string {
    const privateSuffix = message.isPrivate ? ' (private note)' : ''
    return `### ${singleLine(message.authorName)} · ${formatTimestamp(message.createdAt)}${privateSuffix}\n\n${messageBody(message)}`
}

function participantLines(messages: ChatMessage[]): string[] {
    const seen = new Set<string>()
    const lines: string[] = []
    for (const message of messages) {
        const name = singleLine(message.authorName)
        const role = AUTHOR_TYPE_LABELS[message.authorType]
        if (!seen.has(`${name}|${role}`)) {
            seen.add(`${name}|${role}`)
            lines.push(`- ${name} (${role})`)
        }
    }
    return lines
}

/**
 * Serialize a ticket conversation to a portable CommonMark transcript: a metadata header,
 * then one section per message, separated by horizontal rules so message boundaries stay
 * unambiguous even when a message contains its own headings.
 */
export function chatTranscriptMarkdown(
    ticket: Ticket | null,
    messages: ChatMessage[],
    companySummary?: string
): string {
    const parts: string[] = []

    if (ticket) {
        const statusLabel = statusOptionsWithoutAll.find((option) => option.value === ticket.status)?.label
        const priorityLabel = priorityOptions.find((option) => option.value === ticket.priority)?.label
        // The ticket number is a hyperlink so agents reading the transcript can navigate to the ticket
        const ticketUrl = `${window.location.origin}${addProjectIdIfMissing(urls.supportTicketDetail(ticket.ticket_number))}`
        const metadata = [
            ticket.email_subject ? `- Subject: ${singleLine(ticket.email_subject)}` : null,
            `- Channel: ${ticket.channel_source}`,
            statusLabel ? `- Status: ${statusLabel}` : null,
            priorityLabel ? `- Priority: ${priorityLabel}` : null,
            companySummary ? `- Company: ${singleLine(companySummary)}` : null,
            `- Created: ${formatTimestamp(ticket.created_at)}`,
            `- URL: ${ticketUrl}`,
        ].filter(Boolean)
        let header = `# [Support ticket #${ticket.ticket_number}](${ticketUrl})\n\n${metadata.join('\n')}`
        const participants = participantLines(messages)
        if (participants.length > 0) {
            header += `\n\nParticipants:\n\n${participants.join('\n')}`
        }
        parts.push(header)
    }

    parts.push(...messages.map(messageSection))

    return parts.join('\n\n---\n\n').trim() + '\n'
}

// Best-effort: only enriched organizations have a description; anything missing or failing means no line
export async function fetchCompanySummary(organizationId: string): Promise<string | null> {
    try {
        const groupTypes = groupsModel.findMounted()?.values.groupTypes
        const orgTypeIndex = groupTypes
            ? Array.from(groupTypes.values()).find((groupType) => groupType.group_type === 'organization')
                  ?.group_type_index
            : undefined
        if (orgTypeIndex === undefined) {
            return null
        }
        const params = { group_type_index: orgTypeIndex, group_key: organizationId }
        // nosemgrep: prefer-codegen-api
        const group = await api.get<Group>(`api/projects/${getCurrentTeamId()}/groups/find?${toParams(params)}`)
        const properties = group?.group_properties ?? {}
        const description = properties['$enriched_org_description']
        if (typeof description !== 'string' || !description.trim()) {
            return null
        }
        const name = properties['$enriched_org_name'] || properties['name']
        return typeof name === 'string' && name.trim() ? `${name}. ${description}` : description
    } catch {
        return null
    }
}

// The comments API is cursor-paginated at 100 per page; follow `next` so long tickets
// are copied in full. Returned oldest first, matching the transcript order.
async function fetchAllTicketMessages(ticketId: string): Promise<CommentType[]> {
    const all: CommentType[] = []
    let response: CountedPaginatedResponse<CommentType> = await api.comments.list({
        scope: 'conversations_ticket',
        item_id: ticketId,
    })
    all.push(...(response.results || []))
    while (response.next) {
        // The cursor URL comes from the API itself; there is no generated client for following it
        // nosemgrep: prefer-codegen-api
        response = await api.get<CountedPaginatedResponse<CommentType>>(response.next)
        all.push(...(response.results || []))
    }
    return all.reverse()
}

// Lazy-loaded: the o200k ranks are ~2 MB, so they must never enter the main bundle.
// o200k_base is the tiktoken encoding of current OpenAI models; counts for other
// vendors differ slightly, which is fine for a cost indication.
let tokenCounterPromise: Promise<(text: string) => number> | null = null

export function countTranscriptTokens(text: string): Promise<number> {
    if (!tokenCounterPromise) {
        tokenCounterPromise = import('gpt-tokenizer/encoding/o200k_base').then((module) => module.countTokens)
    }
    return tokenCounterPromise.then((countTokens) => countTokens(text))
}

/**
 * Copy the whole conversation to the clipboard as markdown. Uses the already-loaded
 * messages when they are complete; refetches every page first when older messages
 * exist beyond what the view has loaded.
 */
export async function copyChatTranscript(
    ticket: Ticket | null,
    loadedMessages: ChatMessage[],
    hasMoreMessages: boolean
): Promise<void> {
    let messages = loadedMessages
    if (ticket && hasMoreMessages) {
        try {
            messages = (await fetchAllTicketMessages(ticket.id)).map((message) => commentToChatMessage(message, ticket))
        } catch {
            lemonToast.error('Failed to load the full conversation, nothing was copied')
            return
        }
    }
    const companySummary = ticket?.organization_id ? await fetchCompanySummary(ticket.organization_id) : null
    await copyToClipboard(chatTranscriptMarkdown(ticket, messages, companySummary ?? undefined), 'chat transcript')
}
