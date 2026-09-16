import { parseAiBlobPointer } from './aiBlob'
import {
    getGeminiInlineData,
    isAnthropicDocumentMessage,
    isAnthropicImageMessage,
    isGeminiAudioMessage,
    isGeminiDocumentMessage,
    isGeminiImageMessage,
    isOpenAIAudioMessage,
    isOpenAIFileMessage,
    isOpenAIImageURLMessage,
} from './utils'

export type RedactedMediaKind = 'image' | 'file' | 'audio'

// Without enable_full_ai_capture the SDKs drop the payload and leave a marker in its place. The
// wording varies per SDK and per media type, so match the shape rather than a fixed set of strings.
const SENTINEL_RE = /^\s*\[base64\b[^\]]*\bredacted\]\s*$/i
// Deliberately loose: recipes build this prefix by template, so the mime can be absent or carry
// extra parameters. A stricter pattern would let a wrapped sentinel through as a renderable source.
const BASE64_DATA_URI_PREFIX = /^data:[^,]*;base64,/i

export function isRedactedMediaSentinel(value: string): boolean {
    return SENTINEL_RE.test(value.replace(BASE64_DATA_URI_PREFIX, ''))
}

export function isRenderableMediaSource(value: string): boolean {
    if (isRedactedMediaSentinel(value)) {
        return false
    }
    return /^data:/i.test(value) || /^https?:\/\//i.test(value) || parseAiBlobPointer(value) !== null
}

function hasRedactedGeminiInlineData(item: unknown): boolean {
    const inlineData = getGeminiInlineData(item)
    return inlineData !== null && isRedactedMediaSentinel(inlineData.data)
}

/**
 * Classifies a content item that cannot be rendered as media, so the caller can show a placeholder
 * instead of handing the value to the browser as a src. Branches are ordered to match the render
 * ladder in ConversationMessagesDisplay, so the shape judged here is the shape that would render.
 */
export function redactedMediaKind(item: unknown): RedactedMediaKind | null {
    if (!item || typeof item !== 'object' || !('type' in item)) {
        return null
    }

    // A url field has to carry a real source. Anything else, sentinel or not, resolves against the
    // page and 404s, so the whitelist is the gate.
    if (item.type === 'image' && 'image' in item && typeof item.image === 'string') {
        return isRenderableMediaSource(item.image) ? null : 'image'
    }
    if (item.type === 'input_image' && 'image_url' in item && typeof item.image_url === 'string') {
        return isRenderableMediaSource(item.image_url) ? null : 'image'
    }
    if (isOpenAIImageURLMessage(item)) {
        return isRenderableMediaSource(item.image_url.url) ? null : 'image'
    }

    // Payload fields legitimately hold bare base64, which no whitelist can accept, so only the
    // sentinel disqualifies them.
    if (isAnthropicImageMessage(item)) {
        return isRedactedMediaSentinel(item.source.data) ? 'image' : null
    }
    if (isGeminiImageMessage(item)) {
        return hasRedactedGeminiInlineData(item) ? 'image' : null
    }
    if (isOpenAIFileMessage(item)) {
        return isRedactedMediaSentinel(item.file.file_data) ? 'file' : null
    }
    if (isAnthropicDocumentMessage(item)) {
        return isRedactedMediaSentinel(item.source.data) ? 'file' : null
    }
    if (isGeminiDocumentMessage(item)) {
        return hasRedactedGeminiInlineData(item) ? 'file' : null
    }
    if (isOpenAIAudioMessage(item) || isGeminiAudioMessage(item)) {
        return isRedactedMediaSentinel(item.data) ? 'audio' : null
    }

    return null
}
