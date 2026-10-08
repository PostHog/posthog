import { isObject } from 'lib/utils/guards'

import { parseAiBlobPointer, resolveAiBlobUrl, resolveDataUri } from '../../../aiBlob'
import { isRenderableMediaSource } from '../../../mediaSource'
import { AttachmentMediaType, MessagePart } from '../types'

export type AttachmentPart = Extract<MessagePart, { kind: 'attachment' }>

export type TeamId = number | string | null

const MEDIA_TYPE_BY_ITEM_TYPE: Record<string, AttachmentMediaType> = {
    image: 'image',
    image_url: 'image',
    input_image: 'image',
    audio: 'audio',
    input_audio: 'audio',
    video: 'video',
    file: 'file',
    document: 'file',
    input_file: 'file',
}

// Providers nest the payload under one of these keys, each with its own field names.
const NESTED_PAYLOAD_KEYS = ['source', 'file', 'input_audio', 'image_url', 'inline_data', 'inlineData']
const SOURCE_KEYS = ['url', 'file_url', 'image_url', 'file_data', 'image', 'data', 'file']
const MIME_KEYS = ['mediaType', 'mimeType', 'mime_type', 'media_type']
const NAME_KEYS = ['filename', 'name']

const URL_SCHEME = /^[a-z][\w+.-]*:/i
const BASE64 = /^[A-Za-z0-9+/=\s]+$/
const DATA_URI_MIME = /^data:([^;,]+)/i

export function isAttachmentItemType(type: string): boolean {
    return type in MEDIA_TYPE_BY_ITEM_TYPE
}

function readString(containers: Record<string, unknown>[], keys: string[]): string | null {
    for (const key of keys) {
        for (const container of containers) {
            const value = container[key]
            if (typeof value === 'string' && value !== '') {
                return value
            }
        }
    }
    return null
}

function audioFormatMime(containers: Record<string, unknown>[]): string | null {
    const format = readString(containers, ['format'])
    return format ? `audio/${format}` : null
}

function mediaTypeOf(itemType: string, mimeType: string | null): AttachmentMediaType {
    const byItemType = MEDIA_TYPE_BY_ITEM_TYPE[itemType] ?? 'file'
    if (!mimeType) {
        return byItemType
    }
    const topLevel = mimeType.split('/')[0]
    return topLevel === 'image' || topLevel === 'audio' || topLevel === 'video' ? topLevel : 'file'
}

// Raw base64 payloads become data: URIs. The app's CSP allows media only from its own origin, data: and blob:,
// so stored blob pointers must resolve to the same-origin blob endpoint.
function resolveUrl(source: string | null, mimeType: string | null, teamId: TeamId): string | null {
    if (source === null) {
        return null
    }
    if (isRenderableMediaSource(source)) {
        return resolveAiBlobUrl(source, teamId)
    }
    if (URL_SCHEME.test(source) || !mimeType || !BASE64.test(source)) {
        return null
    }
    return resolveDataUri(source, mimeType, teamId)
}

function sourceMime(source: string | null): string | null {
    if (source === null) {
        return null
    }
    return DATA_URI_MIME.exec(source)?.[1] ?? parseAiBlobPointer(source)?.mime ?? null
}

export function toAttachment(item: Record<string, unknown> & { type: string }, teamId: TeamId): AttachmentPart {
    const nested = NESTED_PAYLOAD_KEYS.map((key) => item[key]).filter(isObject)
    const containers = [...nested, item]
    const source = readString(containers, SOURCE_KEYS)
    const mimeType =
        readString(containers, MIME_KEYS) ??
        (item.type === 'input_audio' ? audioFormatMime(containers) : null) ??
        sourceMime(source)
    const mediaType = mediaTypeOf(item.type, mimeType)
    const isKnownMedia = isAttachmentItemType(item.type)
    // Matches the legacy player, which assumes WAV for raw audio sent without a mime type.
    const payloadMime = mimeType ?? (mediaType === 'audio' ? 'audio/wav' : null)
    return {
        kind: 'attachment',
        mediaType,
        name: readString(containers, NAME_KEYS) ?? (isKnownMedia ? null : item.type),
        mimeType,
        url: isKnownMedia ? resolveUrl(source, payloadMime, teamId) : null,
    }
}
