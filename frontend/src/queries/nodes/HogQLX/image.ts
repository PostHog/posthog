const MAX_IMAGE_SOURCE_LENGTH = 64 * 1024
const MAX_IMAGE_DIMENSION = 24
const DATA_IMAGE_SOURCE = /^data:image\/(png|jpeg|gif|webp|avif|svg\+xml)(;(charset=utf-8|utf8))?(;base64)?,/i

export function imageSource(value: unknown): string | null {
    if (typeof value !== 'string' || value.length > MAX_IMAGE_SOURCE_LENGTH) {
        return null
    }
    return DATA_IMAGE_SOURCE.test(value) || isSameOrigin(value) ? value : null
}

function isSameOrigin(value: string): boolean {
    if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
        return false
    }
    try {
        const origin = window.location.origin
        return new URL(value, origin).origin === origin
    } catch {
        return false
    }
}

export function imageDimension(value: unknown): number {
    const size = typeof value === 'number' || typeof value === 'string' ? Number(value) : NaN
    return Number.isFinite(size) && size > 0 ? Math.min(size, MAX_IMAGE_DIMENSION) : MAX_IMAGE_DIMENSION
}
