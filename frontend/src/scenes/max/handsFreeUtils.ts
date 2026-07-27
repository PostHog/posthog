import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'

const VIZ_TYPES = new Set<AssistantMessageType>([
    AssistantMessageType.Visualization,
    AssistantMessageType.MultiVisualization,
    AssistantMessageType.Artifact,
])

export interface AssistantSummary {
    text: string
    vizCount: number
}

export function summariseAssistantThread(
    messages: { type: AssistantMessageType; content?: unknown }[]
): AssistantSummary {
    let humanCutoff = -1
    for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].type === AssistantMessageType.Human) {
            humanCutoff = i
            break
        }
    }

    let latestProse = ''
    let vizCount = 0
    for (let i = humanCutoff + 1; i < messages.length; i++) {
        const msg = messages[i]
        if (VIZ_TYPES.has(msg.type)) {
            vizCount += 1
            continue
        }
        if (msg.type === AssistantMessageType.Assistant && typeof msg.content === 'string' && msg.content) {
            latestProse = msg.content
        }
    }
    return { text: latestProse, vizCount }
}

export function buildSpokenText(summary: AssistantSummary): string {
    const stripped = stripMarkdown(summary.text).trim()
    if (summary.vizCount === 0) {
        return stripped
    }
    const suffix =
        summary.vizCount === 1
            ? "I've added 1 chart to the chat."
            : `I've added ${summary.vizCount} charts to the chat.`
    return stripped ? `${stripped} ${suffix}` : suffix
}

export function stripMarkdown(text: string): string {
    return (
        text
            // fenced code blocks - replaced wholesale; never spoken
            .replace(/```[\s\S]*?```/g, ' (code block omitted) ')
            // inline code
            .replace(/`([^`]+)`/g, '$1')
            // images
            .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
            // links - keep link text
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
            // tables - drop row-separator lines (| --- |) and pipe characters elsewhere
            .replace(/^\s*\|?\s*:?-{2,}:?(\s*\|\s*:?-{2,}:?)*\s*\|?\s*$/gm, '')
            .replace(/\|/g, ' ')
            // headings
            .replace(/^#+\s*/gm, '')
            // bold - **foo** or __foo__ - run twice to safely handle nested markers
            .replace(/\*\*([^*]+?)\*\*/g, '$1')
            .replace(/__([^_]+?)__/g, '$1')
            // italic - *foo* or _foo_ - but only when the marker is at a word boundary so
            // identifiers like foo_bar_baz aren't mangled
            .replace(/(^|[^A-Za-z0-9_])[*_]([^*_\n]+?)[*_](?=$|[^A-Za-z0-9_])/g, '$1$2')
            // strikethrough
            .replace(/~~([^~]+?)~~/g, '$1')
            // blockquotes
            .replace(/^\s*>\s?/gm, '')
            // bulleted lists
            .replace(/^\s*[-*+]\s+/gm, '')
            // ordered lists
            .replace(/^\s*\d+[.)]\s+/gm, '')
            // collapse runs of whitespace - TTS reads runs of "\n\n" as awkward pauses
            .replace(/\s+/g, ' ')
    )
}
