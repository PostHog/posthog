import { isObject } from 'lib/utils/guards'

import { normalizeMessages } from '../../../messageNormalization'
import { CompatMessage } from '../../../types'
import { INTERNAL_THINKING_ROLE, INTERNAL_TOOL_RESULT_ROLE, extractText, extractTextContent } from '../../../utils'
import { MessagePart, MessageRole, ThreadMessage } from '../types'
import { TeamId, isAttachmentItemType, toAttachment } from './toAttachment'

const TEXT_ITEM_TYPES = new Set(['text', 'input_text', 'output_text'])
const SKIPPED_ROLES = new Set(['available tools'])
const LANGCHAIN_MESSAGE_TYPES = new Set(['system', 'human', 'ai', 'tool', 'function', 'chat'])

type ToolCallPart = Extract<MessagePart, { kind: 'toolCall' }>
type ContentItem = Record<string, unknown> & { type: string }

export interface ThreadMessagesOptions {
    defaultRole: 'user' | 'assistant'
    idPrefix: string
    sourceNodeId: string | null
    teamId: TeamId
}

function isContentItem(item: unknown): item is ContentItem {
    return isObject(item) && typeof item.type === 'string'
}

function parseArguments(args: unknown): unknown {
    if (typeof args !== 'string') {
        return args
    }
    try {
        return JSON.parse(args)
    } catch {
        return args
    }
}

// The normalizer passes some media items it has no recipe for through as their JSON text.
function parseMediaItem(content: string): ContentItem | null {
    if (!content.startsWith('{')) {
        return null
    }
    const parsed = parseArguments(content)
    return isContentItem(parsed) && isAttachmentItemType(parsed.type) ? parsed : null
}

function itemText(item: unknown): string | undefined {
    if (isContentItem(item) && TEXT_ITEM_TYPES.has(item.type) && typeof item.text === 'string') {
        return item.text
    }
    return extractTextContent(item)
}

function contentText(message: CompatMessage): string {
    if (!Array.isArray(message.content)) {
        return extractText(message)
    }
    return message.content
        .map(itemText)
        .filter((text): text is string => text !== undefined)
        .join('\n')
}

// OpenAI puts a refusal or a spoken reply next to `content`, which is then null.
function sideChannelTexts(message: CompatMessage): string[] {
    const refusal: unknown = message.refusal
    const audio: unknown = message.audio
    const transcript = isObject(audio) ? audio.transcript : undefined
    return [refusal, transcript].filter((text): text is string => typeof text === 'string' && text !== '')
}

function messageText(message: CompatMessage): string {
    return [contentText(message), ...sideChannelTexts(message)].filter((text) => text !== '').join('\n')
}

function contentParts(message: CompatMessage, teamId: TeamId): { text: string; attachments: MessagePart[] } {
    const mediaItem = typeof message.content === 'string' ? parseMediaItem(message.content) : null
    if (mediaItem) {
        return { text: '', attachments: [toAttachment(mediaItem, teamId)] }
    }
    const items: unknown[] = Array.isArray(message.content) ? message.content : []
    return {
        text: messageText(message),
        attachments: items
            .filter(isContentItem)
            .filter((item) => !TEXT_ITEM_TYPES.has(item.type))
            .map((item) => toAttachment(item, teamId)),
    }
}

function toRole(role: string): MessageRole {
    if (role === 'developer') {
        return 'system'
    }
    if (role === 'system' || role === 'user' || role === 'tool') {
        return role
    }
    return role === INTERNAL_TOOL_RESULT_ROLE ? 'tool' : 'assistant'
}

function isEmptyIO(value: unknown): boolean {
    return value === null || value === undefined || value === ''
}

// The normalizer's catch-all recipe accepts any array, so its `recognized` flag cannot tell messages from
// workflow state. Only role-bearing messages and LangChain message dicts count.
function isMessageLike(item: unknown): boolean {
    if (!isObject(item)) {
        return false
    }
    if (typeof item.role === 'string') {
        return true
    }
    return typeof item.type === 'string' && LANGCHAIN_MESSAGE_TYPES.has(item.type) && 'content' in item
}

function isMessageArray(raw: unknown): boolean {
    return Array.isArray(raw) && raw.length > 0 && raw.every(isMessageLike)
}

export function toThreadMessages(
    raw: unknown,
    { defaultRole, idPrefix, sourceNodeId, teamId }: ThreadMessagesOptions
): ThreadMessage[] {
    if (isEmptyIO(raw)) {
        return []
    }
    const compat: CompatMessage[] = normalizeMessages(raw, defaultRole).messages
    const pendingCalls = new Map<string, ToolCallPart>()
    const messages: ThreadMessage[] = []

    compat.forEach((message, index) => {
        if (SKIPPED_ROLES.has(message.role)) {
            return
        }
        const role = toRole(message.role)
        const { text, attachments } = contentParts(message, teamId)

        // A tool call part holds its result as text only, so a result carrying media stays its own
        // message and keeps its attachments.
        const pendingCall =
            role === 'tool' && message.tool_call_id && attachments.length === 0
                ? pendingCalls.get(message.tool_call_id)
                : undefined
        if (pendingCall && message.tool_call_id) {
            pendingCall.result = text || message.content
            pendingCalls.delete(message.tool_call_id)
            return
        }

        const parts: MessagePart[] = []
        if (text) {
            parts.push(message.role === INTERNAL_THINKING_ROLE ? { kind: 'thinking', text } : { kind: 'text', text })
        }
        parts.push(...attachments)
        for (const toolCall of message.tool_calls ?? []) {
            const part: ToolCallPart = {
                kind: 'toolCall',
                name: toolCall.function.name,
                args: parseArguments(toolCall.function.arguments),
            }
            if (toolCall.id) {
                pendingCalls.set(toolCall.id, part)
            }
            parts.push(part)
        }
        if (parts.length === 0) {
            return
        }
        messages.push({
            id: `${idPrefix}-${index}`,
            role,
            parts,
            isInternal: role === 'tool' || parts.every((part) => part.kind === 'thinking' || part.kind === 'toolCall'),
            sourceNodeId,
        })
    })
    return messages
}

export function isMessageIO(input: unknown, output: unknown): boolean {
    const captured = [input, output].filter((value) => !isEmptyIO(value))
    return (
        captured.some(isMessageArray) && captured.every((value) => typeof value === 'string' || isMessageArray(value))
    )
}
