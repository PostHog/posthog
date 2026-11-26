/**
 * The lines `POST dashboard_v2/query_batch/` streams back as NDJSON. The stream is not described in the OpenAPI
 * schema, so these types follow `products/dashboards/backend/v2/query_batch.py` (`_result_line`) and
 * `products/dashboards/backend/v2/frames.py` (`frame_json`).
 */

export interface FrameField {
    name: string
    type: 'time' | 'number' | 'string' | 'boolean' | 'other'
    /** A time field holds epoch milliseconds. A number field holds null for a gap. */
    values: unknown[]
    unit?: string
    labels?: Record<string, string>
}

export interface Frame {
    name: string | null
    labels: Record<string, string>
    fields: FrameField[]
    meta: { interval?: string | null; end?: number | null; truncated?: boolean; previous?: boolean }
    hash: string
}

export interface QueryBatchLine {
    i: number
    refId?: string
    error?: string
    /** Set with `error` when a frames request ran but its result has no frame shape: the query's node kind or language. */
    unsupported_shape?: string
    result?: {
        /** A frames request always comes back as `frames`, or as a line with `error`. */
        format?: 'frames' | 'result'
        frames?: Frame[]
        canonical?: string
        /** Freshness and access-control notes that qualify the frames. */
        warnings?: { message: string }[]
        cache?: { fetchedAt?: string | null; stale?: boolean; hit?: boolean }
    } | null
}

export async function readNdjson(
    body: ReadableStream<Uint8Array>,
    onLine: (line: QueryBatchLine) => void,
    onChunk?: (byteLength: number) => void
): Promise<void> {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    const emit = (text: string): void => {
        if (!text.trim()) {
            return
        }
        try {
            onLine(JSON.parse(text))
        } catch {
            // One unreadable line must not lose the rest of the board.
        }
    }
    while (true) {
        const { done, value } = await reader.read()
        if (value) {
            onChunk?.(value.byteLength)
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() ?? ''
            lines.forEach(emit)
        }
        if (done) {
            emit(buffer + decoder.decode())
            return
        }
    }
}
