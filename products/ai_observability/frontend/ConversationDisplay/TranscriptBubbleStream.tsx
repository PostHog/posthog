import posthog from 'posthog-js'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { MessageTemplate, parseSandboxQuestions } from 'products/posthog_ai/frontend/api/primitives'

import { CompatMessage } from '../types'
import {
    AVAILABLE_TOOLS_ROLE,
    INTERNAL_THINKING_ROLE,
    INTERNAL_TOOL_RESULT_ROLE,
    extractInternalContent,
    extractText,
    extractTextContent,
    getInternalTagName,
    isInternalToolResultUserMessage,
    isToolStepItem,
    parseToolArgumentsForDisplay,
} from '../utils'

// Roles that carry no user-visible content in a chat-app view. System prompts
// and the synthetic "available tools" message are noise here; their effects are
// visible through the assistant's behavior, and the full message tree is still
// one click away via "Show steps".
const HIDDEN_ROLES = new Set<string>(['system', AVAILABLE_TOOLS_ROLE])

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

// An item in the rendered transcript stream. Bubbles render as `MessageTemplate`s.
// Internal groups render as a single collapsed pill where the hidden messages
// would have sat — preserving chronological position without polluting the chat.
// "Internal" covers framework prompt tag wrappers, model reasoning/thinking parts,
// and tool-call results — anything the user didn't write and didn't ask to see.
type StreamItem =
    | { kind: 'bubble'; message: CompatMessage; text: string; nonText: boolean }
    | { kind: 'internal-group'; messages: CompatMessage[]; labels: string[]; role: string }

type SessionEntry =
    | { kind: 'bubble'; message: CompatMessage; text: string; nonText: boolean }
    | { kind: 'internal'; message: CompatMessage; label: string }

// Returns a short label identifying *why* a message is internal. Returns
// `undefined` for messages that should render as normal bubbles.
function getInternalLabel(message: CompatMessage): string | undefined {
    if (message.role === INTERNAL_THINKING_ROLE) {
        return 'thinking'
    }
    // `assistant (tool result)` is the normalized role; raw `tool` results (OpenAI chat, LangChain,
    // OTel, OpenAI Agents SDK) keep `role: 'tool'` and would otherwise leak as visible bubbles.
    if (message.role === INTERNAL_TOOL_RESULT_ROLE || message.role === 'tool') {
        return 'tool_result'
    }
    const internalTag = getInternalTagName(message)
    if (internalTag !== undefined) {
        return internalTag
    }
    if (isInternalToolResultUserMessage(message)) {
        return 'tool_result'
    }
    return undefined
}

// Normalized tool calls are always `undefined` or non-empty (the coercer drops empty arrays).
function isToolCallMessage(message: CompatMessage): boolean {
    return Array.isArray(message.tool_calls) && message.tool_calls.length > 0
}

function isToolResultEntry(message: CompatMessage): boolean {
    return (
        message.role === INTERNAL_TOOL_RESULT_ROLE ||
        message.role === 'tool' ||
        isInternalToolResultUserMessage(message)
    )
}

// A user-authored message — not a framework tool-result-user message and not a tag wrapper.
function isGenuineUserMessage(message: CompatMessage): boolean {
    return message.role === 'user' && getInternalLabel(message) === undefined
}

// An assistant text message is an intermediate "step" (narration/preamble), not the final answer,
// when it either makes a tool call itself, or is followed by tool activity before the turn yields
// back to the user. Only the final assistant text (no trailing tool activity) stays a bubble.
function isIntermediateAssistantText(messages: CompatMessage[], index: number): boolean {
    const message = messages[index]
    if (message.role !== 'assistant') {
        return false
    }
    if (isToolCallMessage(message)) {
        return true
    }
    for (let j = index + 1; j < messages.length; j++) {
        if (isGenuineUserMessage(messages[j])) {
            return false
        }
        if (isToolCallMessage(messages[j]) || isToolResultEntry(messages[j])) {
            return true
        }
    }
    return false
}

const AGENT_SIDE_LABELS = new Set<string>(['thinking', 'tool_result', 'reasoning'])

function pillSideFor(labels: string[]): 'left' | 'right' {
    return labels.length > 0 && AGENT_SIDE_LABELS.has(labels[0]) ? 'left' : 'right'
}

// Only a tool we know asks the user may render its payload as speech, because routine trailing
// calls like git_commit(message=…) can carry text-like arguments too. Exact names, so nothing
// over-fires; an unknown ask tool keeps the hidden pill until its name is added here. The
// normalization makes one entry cover the camelCase, snake_case, and kebab-case spellings.
const ASK_TOOL_NAMES = new Set(['askuserquestion', 'askfollowupquestion', 'askhuman', 'askuser', 'requestuserinput'])

function isAskLikeToolName(name: unknown): boolean {
    return typeof name === 'string' && ASK_TOOL_NAMES.has(name.toLowerCase().replace(/[^a-z0-9]/g, ''))
}

function hasAskLikeCall(message: CompatMessage): boolean {
    return (message.tool_calls ?? []).some((call) => isAskLikeToolName(call.function?.name))
}

function askQuestionText(message: CompatMessage): string {
    return (message.tool_calls ?? [])
        .filter((call) => isAskLikeToolName(call.function?.name))
        .map((call) => parseToolArgumentsForDisplay(call.function?.arguments))
        .flatMap((parsed) => (parsed.kind === 'parsed' ? parseSandboxQuestions(parsed.value) : []))
        .map((question) => question.question.trim())
        .filter((text) => text.length > 0)
        .join('\n\n')
}

function isPlainAssistant(message: CompatMessage): boolean {
    return message.role === 'assistant' && getInternalLabel(message) === undefined
}

// Trailing messages that do not end the turn. A tool result does end it, because it means the
// call was answered and the turn moved on.
function isTailSkippable(message: CompatMessage): boolean {
    if (isToolResultEntry(message)) {
        return false
    }
    if (HIDDEN_ROLES.has(message.role) || getInternalLabel(message) !== undefined) {
        return true
    }
    return extractText(message).trim().length === 0 && !hasNonTextContent(message) && !isToolCallMessage(message)
}

interface TrailingAsk {
    anchorIndex: number
    text: string
    consumedIndices: Set<number>
}

// A turn that ends on an ask-like call is the assistant handing the turn to the user, which
// makes it the turn's content. Providers split one turn into different message shapes, so the
// unit is the whole trailing run: spoken words win, the ask call's arguments are the fallback.
function findTrailingAsk(messages: CompatMessage[]): TrailingAsk | null {
    const tailStart = messages.findLastIndex((message) => !isPlainAssistant(message) && !isTailSkippable(message)) + 1
    const assistantEntries = messages
        .slice(tailStart)
        .map((message, offset) => ({ message, index: tailStart + offset }))
        .filter(({ message }) => isPlainAssistant(message))
    if (!assistantEntries.some(({ message }) => hasAskLikeCall(message))) {
        return null
    }
    const spoken = assistantEntries
        .map(({ message }) => extractText(message).trim())
        .filter((text) => text.length > 0)
        .join('\n\n')
    const text =
        spoken || assistantEntries.map(({ message }) => askQuestionText(message)).find((t) => t.length > 0) || ''
    if (!text) {
        return null
    }
    const consumed = assistantEntries.filter(
        ({ message }) => hasAskLikeCall(message) || extractText(message).trim().length > 0
    )
    return {
        anchorIndex: consumed[consumed.length - 1].index,
        text,
        consumedIndices: new Set(consumed.map(({ index }) => index)),
    }
}

function classifyMessages(messages: CompatMessage[]): SessionEntry[] {
    const trailingAsk = findTrailingAsk(messages)
    const result: SessionEntry[] = []
    for (let i = 0; i < messages.length; i++) {
        const message = messages[i]
        if (HIDDEN_ROLES.has(message.role)) {
            continue
        }
        const internalLabel = getInternalLabel(message)
        if (internalLabel !== undefined) {
            result.push({ kind: 'internal', message, label: internalLabel })
            continue
        }
        if (trailingAsk !== null && i === trailingAsk.anchorIndex) {
            // nonText stays false: the ask is rendered, so the unrenderable capture would misfire.
            result.push({ kind: 'bubble', message, text: trailingAsk.text, nonText: false })
            continue
        }
        if (trailingAsk?.consumedIndices.has(i)) {
            continue
        }
        const text = extractText(message)
        const nonText = hasNonTextContent(message)
        if (text.length === 0 && !nonText) {
            continue
        }
        // Assistant narration that precedes/accompanies tool use is an intermediate step, not the
        // final answer — collapse it into the internal pill alongside thinking and tool results.
        if (isIntermediateAssistantText(messages, i)) {
            result.push({ kind: 'internal', message, label: 'reasoning' })
            continue
        }
        result.push({ kind: 'bubble', message, text, nonText })
    }
    return result
}

function groupInternal(classified: SessionEntry[]): StreamItem[] {
    const result: StreamItem[] = []
    let pending: Extract<SessionEntry, { kind: 'internal' }>[] = []
    const makeGroup = (): void => {
        if (pending.length === 0) {
            return
        }
        result.push({
            kind: 'internal-group',
            messages: pending.map((b) => b.message),
            labels: pending.map((b) => b.label),
            role: pending[0].message.role,
        })
        pending = []
    }
    for (const item of classified) {
        if (item.kind === 'internal') {
            pending.push(item)
            continue
        }
        makeGroup()
        result.push({ kind: 'bubble', message: item.message, text: item.text, nonText: item.nonText })
    }
    makeGroup()
    return result
}

// Exported so the test can pin the grouping logic without rendering React.
export function buildStreamItems(messages: CompatMessage[]): StreamItem[] {
    return groupInternal(classifyMessages(messages))
}

/**
 * Renders a deduplicated turn as a chat-app-style bubble stream — user on the
 * right, everything else (assistant, tool responses, etc.) on the left. Skips
 * `system` and `available tools` pseudo-messages; their context is implicit in
 * the assistant's reply and reachable via the per-turn "Show steps" panel.
 * Framework prompt tag-wrapper messages (e.g. `<system_reminder>...`) are collapsed.
 *
 * Deliberately minimal otherwise: no headers, no per-message expand toggles, no
 * metadata row, no playground button. The Trace page's `ConversationMessagesDisplay`
 * covers those cases; this surface optimizes for top-to-bottom readability.
 */
export function TranscriptBubbleStream({
    inputs,
    outputs,
    hideInternal = false,
}: {
    inputs: CompatMessage[]
    outputs: CompatMessage[]
    hideInternal?: boolean
}): JSX.Element | null {
    const items = useMemo(
        () => buildStreamItems([...inputs, ...outputs]).filter((item) => !hideInternal || item.kind === 'bubble'),
        [inputs, outputs, hideInternal]
    )

    const capturedRef = useRef<Set<string>>(new Set())
    useEffect(() => {
        for (const item of items) {
            if (item.kind === 'bubble' && item.nonText) {
                captureUnrenderableMessageOnce(item.message, capturedRef.current)
            }
        }
    }, [items])

    if (items.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1.5">
            {items.map((item, i) =>
                item.kind === 'bubble' ? (
                    <MessageTemplate
                        key={i}
                        type={item.message.role === 'user' ? 'human' : 'ai'}
                        wrapperClassName="max-w-[75%]"
                        // Same user-message fill the Trace page uses, so the two sides don't blend together
                        boxClassName={item.message.role === 'user' ? 'bg-fill-tertiary' : undefined}
                    >
                        {item.text && <CollapsibleBubbleText text={item.text} />}
                        {item.nonText && <div className="italic text-muted text-xs mt-1">(has attachments)</div>}
                    </MessageTemplate>
                ) : (
                    <InternalGroupPill key={i} messages={item.messages} labels={item.labels} role={item.role} />
                )
            )}
        </div>
    )
}

// Character count approximates rendered height without measuring the DOM.
const LONG_MESSAGE_CHARS = 1500
const LONG_MESSAGE_LINES = 20

function isLongMessage(text: string): boolean {
    return text.length > LONG_MESSAGE_CHARS || text.split('\n').length > LONG_MESSAGE_LINES
}

function CollapsibleBubbleText({ text }: { text: string }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    // Trace content is untrusted, so external images must not auto-load.
    const markdown = (
        <LemonMarkdown className="whitespace-pre-wrap break-words" disableImages>
            {text}
        </LemonMarkdown>
    )
    if (!isLongMessage(text)) {
        return markdown
    }
    const collapsed = !expanded
    return (
        <div className="flex flex-col gap-1">
            <div className={collapsed ? 'max-h-60 overflow-hidden' : undefined}>{markdown}</div>
            <LemonButton
                size="xsmall"
                type="tertiary"
                className="self-start"
                onClick={() => setExpanded((v) => !v)}
                data-attr="llm-session-toggle-long-message"
            >
                {collapsed ? 'Show more' : 'Show less'}
            </LemonButton>
        </div>
    )
}

function InternalGroupPill({
    messages,
    labels,
    role: _role,
}: {
    messages: CompatMessage[]
    labels: string[]
    role: string
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const distinctLabels = useMemo(() => Array.from(new Set(labels)), [labels])
    const count = messages.length
    const label = count === 1 ? '1 hidden internal message' : `${count} hidden internal messages`
    const side = pillSideFor(labels)
    const alignSelf = side === 'right' ? 'self-end' : 'self-start'
    const buttonAlignSelf = side === 'right' ? 'self-end' : 'self-start'
    return (
        <div className={`flex flex-col gap-1 text-xs text-muted max-w-[75%] ${alignSelf}`}>
            <button
                type="button"
                className={`flex items-center gap-1 hover:text-default text-left cursor-pointer ${buttonAlignSelf}`}
                onClick={() => setExpanded((v) => !v)}
            >
                <IconChevronRight className={`transition-transform ${expanded ? 'rotate-90' : ''}`} />
                <span>{expanded ? `Hide ${label}` : `Show ${label}`}</span>
                {distinctLabels.length > 0 && (
                    <span className="font-mono opacity-60">— {distinctLabels.join(', ')}</span>
                )}
            </button>
            {expanded && (
                <div className="flex flex-col gap-1.5 opacity-70">
                    {messages.map((m, i) => (
                        <pre
                            key={i}
                            className="font-mono whitespace-pre-wrap break-words text-xs m-0 px-2 py-1 bg-bg-light rounded border"
                        >
                            {extractInternalContent(m)}
                        </pre>
                    ))}
                </div>
            )}
        </div>
    )
}
