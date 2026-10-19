const MAX_IMAGE_SOURCE_LENGTH = 1024 * 1024
const DATA_IMAGE_SOURCE = /^data:image\/(png|jpeg|gif|webp|avif|svg\+xml)(;(charset=utf-8|utf8))?(;base64)?,/i

export function imageSource(value: unknown): string | null {
    if (typeof value !== 'string' || value.length === 0 || value.length > MAX_IMAGE_SOURCE_LENGTH) {
        return null
    }
    if (DATA_IMAGE_SOURCE.test(value)) {
        return value
    }
    try {
        if (value.startsWith('/') && !value.startsWith('//') && !value.includes('\\')) {
            const origin = window.location.origin
            return new URL(value, origin).origin === origin ? value : null
        }
        return new URL(value).protocol === 'https:' ? value : null
    } catch {
        return null
    }
}

export function imageDimension(value: unknown): number {
    const size = typeof value === 'number' || typeof value === 'string' ? Number(value) : NaN
    return Number.isFinite(size) && size > 0 ? Math.min(size, 256) : 32
}
