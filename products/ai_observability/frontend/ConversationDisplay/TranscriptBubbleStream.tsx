import posthog from 'posthog-js'
import { useEffect, useMemo, useRef } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { MessageTemplate } from 'scenes/max/messages/MessageTemplate'

import { CompatMessage } from '../types'
import { AVAILABLE_TOOLS_ROLE, extractTextContent, hasStringContentField, isToolStepItem } from '../utils'

// Roles that carry no user-visible content in a chat-app view. System prompts
// and the synthetic "available tools" message are noise here; their effects are
// visible through the assistant's behavior, and the full message tree is still
// one click away via "Show steps".
const HIDDEN_ROLES = new Set<string>(['system', AVAILABLE_TOOLS_ROLE])

function extractText(message: CompatMessage): string {
    const content = message.content
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        const parts: string[] = []
        for (const part of content) {
            const text = extractTextContent(part)
            if (text !== undefined) {
                parts.push(text)
            }
        }
        return parts.join('\n')
    }
    if (hasStringContentField(content)) {
        return content.content
    }
    return ''
}

function isUnrenderableContentItem(item: unknown): boolean {
    return extractTextContent(item) === undefined && !isToolStepItem(item)
}

export function hasNonTextContent(message: CompatMessage): boolean {
    const content = message.content
    if (!Array.isArray(content)) {
        return false
    }
    return content.some(isUnrenderableContentItem)
}

// Item kinds for the analytics capture, so we can pivot by what we failed to render.
export function unrenderableContentKinds(message: CompatMessage): string[] {
    const content = message.content
    if (!Array.isArray(content)) {
        return []
    }
    const kinds = content
        .filter(isUnrenderableContentItem)
        .map((item) => (typeof item === 'object' && item !== null && 'type' in item ? String(item.type) : typeof item))
    return Array.from(new Set(kinds)).sort()
}

// Content-hash so the analytics capture dedups across kea selector recomputes
// (a sibling turn's `loadFullTrace` invalidates every turn's `newInputs` reference).
function unrenderableKey(message: CompatMessage): string {
    let serialized: string
    try {
        serialized = JSON.stringify(message.content)
    } catch {
        serialized = String(message.content)
    }
    return `${message.role}::${serialized}`
}

export function captureUnrenderableMessageOnce(message: CompatMessage, seen: Set<string>): void {
    const key = unrenderableKey(message)
    if (seen.has(key)) {
        return
    }
    seen.add(key)
    posthog.capture('llma transcript message unrenderable', {
        role: message.role,
        content_kinds: unrenderableContentKinds(message),
    })
}

/**
 * Renders a deduplicated turn as a chat-app-style bubble stream — user on the
 * right, everything else (assistant, tool responses, etc.) on the left. Skips
 * `system` and `available tools` pseudo-messages; their context is implicit in
 * the assistant's reply and reachable via the per-turn "Show steps" panel.
 *
 * Deliberately minimal: no headers, no per-message expand toggles, no metadata
 * row, no playground button. The Trace page's `ConversationMessagesDisplay`
 * covers those cases; this surface optimizes for top-to-bottom readability.
 */
export function TranscriptBubbleStream({
    inputs,
    outputs,
}: {
    inputs: CompatMessage[]
    outputs: CompatMessage[]
}): JSX.Element | null {
    const visible = useMemo(() => {
        return [...inputs, ...outputs]
            .filter((m) => !HIDDEN_ROLES.has(m.role))
            .map((m) => ({ message: m, text: extractText(m), nonText: hasNonTextContent(m) }))
            .filter(({ text, nonText }) => text.length > 0 || nonText)
    }, [inputs, outputs])

    const capturedRef = useRef<Set<string>>(new Set())
    useEffect(() => {
        for (const { message, nonText } of visible) {
            if (nonText) {
                captureUnrenderableMessageOnce(message, capturedRef.current)
            }
        }
    }, [visible])

    if (visible.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1.5">
            {visible.map(({ message, text, nonText }, i) => (
                <MessageTemplate key={i} type={message.role === 'user' ? 'human' : 'ai'} wrapperClassName="max-w-[75%]">
                    {text && <LemonMarkdown className="whitespace-pre-wrap break-words">{text}</LemonMarkdown>}
                    {nonText && <div className="italic text-muted text-xs mt-1">(has attachments)</div>}
                </MessageTemplate>
            ))}
        </div>
    )
}
