export const MESSAGE_MAX_BYTES = 40_000_000
const HEADERS_AND_MIME_BOUNDARIES_BYTES = 64 * 1024

// A file travels as Base64 in lines of 76 characters, each ending in CRLF.
const encodedFileBytes = (size: number): number => Math.ceil((Math.ceil(size / 3) * 4 * 78) / 76)

export function estimateMessageBytes(fileSizes: readonly number[]): number {
    return fileSizes.reduce((total, size) => total + encodedFileBytes(size), HEADERS_AND_MIME_BOUNDARIES_BYTES)
}
