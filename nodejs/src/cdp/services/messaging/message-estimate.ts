export const MESSAGE_MAX_BYTES = 40_000_000
const HEADERS_AND_MIME_BOUNDARIES_BYTES = 64 * 1024
const SUBJECT_BYTES_PER_ENCODED_WORD = 42
const FOLDED_ENCODED_WORD_BYTES = 75

const base64TransferBytes = (size: number): number => Math.ceil((Math.ceil(size / 3) * 4 * 78) / 76)

const encodedSubjectBytes = (subject: string): number =>
    Math.ceil(Buffer.byteLength(subject, 'utf8') / SUBJECT_BYTES_PER_ENCODED_WORD) * FOLDED_ENCODED_WORD_BYTES

export function estimateMessageBytes(
    fileSizes: readonly number[],
    bodies: readonly string[] = [],
    subject = ''
): number {
    const bodySizes = bodies.map((body) => Buffer.byteLength(body, 'utf8'))
    return [...fileSizes, ...bodySizes].reduce(
        (total, size) => total + base64TransferBytes(size),
        HEADERS_AND_MIME_BOUNDARIES_BYTES + encodedSubjectBytes(subject)
    )
}
