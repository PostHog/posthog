// Trace ids are free-form, and the server decodes "%2F" before routing, so a raw id with a "/" cannot travel
// as one path segment. The trace endpoint takes the unpadded base64url of the id's UTF-8 bytes instead.
// Keep this in sync with decode_trace_id_segment in the backend presentation layer.
export function encodeTraceIdSegment(traceId: string): string {
    const binary = Array.from(new TextEncoder().encode(traceId), (byte) => String.fromCharCode(byte)).join('')
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
