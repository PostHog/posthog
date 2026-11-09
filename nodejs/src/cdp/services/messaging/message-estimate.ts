export const MESSAGE_MAX_BYTES = 40_000_000
const HEADERS_AND_MIME_BOUNDARIES_BYTES = 64 * 1024

const base64TransferBytes = (size: number): number => Math.ceil((Math.ceil(size / 3) * 4 * 78) / 76)

export function estimateMessageBytes(fileSizes: readonly number[], bodies: readonly string[] = []): number {
    const bodySizes = bodies.map((body) => Buffer.byteLength(body, 'utf8'))
    return [...fileSizes, ...bodySizes].reduce(
        (total, size) => total + base64TransferBytes(size),
        HEADERS_AND_MIME_BOUNDARIES_BYTES
    )
}
