import { isObject } from 'lib/utils/guards'

import { parseAiBlobPointer } from './aiBlob'
import {
    isAnthropicDocumentMessage,
    isAnthropicImageMessage,
    isGeminiAudioMessage,
    isGeminiDocumentMessage,
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

function hasRedactedMediaData(item: unknown): boolean {
    if (!isObject(item)) {
        return false
    }
    return [item, item.inline_data, item.inlineData, item.source].some(
        (payload) => isObject(payload) && typeof payload.data === 'string' && isRedactedMediaSentinel(payload.data)
    )
}

/** Only explicit SDK redaction markers imply that media was not captured. */
export function redactedMediaKind(item: unknown): RedactedMediaKind | null {
    if (!item || typeof item !== 'object' || !('type' in item)) {
        return null
    }

    if (item.type === 'image') {
        // Legacy messages wrap one image payload in content. Inspect that level only, so cycles
        // cannot recurse; non-image MIME payloads retain Gemini's document classification.
        const legacyContent = 'content' in item && isObject(item.content) ? { ...item.content, type: 'image' } : null
        for (const image of [item, legacyContent]) {
            if (!image) {
                continue
            }
            if (
                (!isGeminiDocumentMessage(image) &&
                    (hasRedactedMediaData(image) ||
                        ('uri' in image && typeof image.uri === 'string' && isRedactedMediaSentinel(image.uri)))) ||
                ('image' in image && typeof image.image === 'string' && isRedactedMediaSentinel(image.image))
            ) {
                return 'image'
            }
        }
    }

    if (item.type === 'input_image' && 'image_url' in item && typeof item.image_url === 'string') {
        return isRedactedMediaSentinel(item.image_url) ? 'image' : null
    }
    if (isOpenAIImageURLMessage(item)) {
        return isRedactedMediaSentinel(item.image_url.url) ? 'image' : null
    }

    // Payload fields legitimately hold bare base64, which no whitelist can accept, so only the
    // sentinel disqualifies them.
    if (isAnthropicImageMessage(item)) {
        return isRedactedMediaSentinel(item.source.data) ? 'image' : null
    }
    if (isOpenAIFileMessage(item)) {
        return isRedactedMediaSentinel(item.file.file_data) ? 'file' : null
    }
    if (isAnthropicDocumentMessage(item)) {
        return isRedactedMediaSentinel(item.source.data) ? 'file' : null
    }
    if (isGeminiDocumentMessage(item)) {
        return hasRedactedMediaData(item) ? 'file' : null
    }
    if (isOpenAIAudioMessage(item) || isGeminiAudioMessage(item)) {
        return isRedactedMediaSentinel(item.data) ? 'audio' : null
    }

    return null
}
