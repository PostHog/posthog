import { isUUIDLike } from 'lib/utils/guards'
import { clamp } from 'lib/utils/numbers'

const MAX_IMAGE_SOURCE_LENGTH = 64 * 1024
const MAX_IMAGE_DIMENSION = 24
const DATA_IMAGE_SOURCE = /^data:image\/(png|jpeg|gif|webp|avif|svg\+xml)(;(charset=utf-8|utf8))?(;base64)?,/i
// Other same-origin paths can redirect off-site, so only the uploaded media route, which serves bytes, is allowed.
const UPLOADED_MEDIA_PREFIX = '/uploaded_media/'

export function imageSource(value: unknown): string | null {
    if (typeof value !== 'string' || value.length > MAX_IMAGE_SOURCE_LENGTH) {
        return null
    }
    if (DATA_IMAGE_SOURCE.test(value)) {
        return value
    }
    return value.startsWith(UPLOADED_MEDIA_PREFIX) && isUUIDLike(value.slice(UPLOADED_MEDIA_PREFIX.length))
        ? value
        : null
}

export function imageDimension(value: unknown): number {
    const size = typeof value === 'number' || typeof value === 'string' ? Number(value) : NaN
    return Number.isFinite(size) && size > 0 ? clamp(size, 0, MAX_IMAGE_DIMENSION) : MAX_IMAGE_DIMENSION
}
