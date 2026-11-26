import type { GrpcTransportOptions } from '@connectrpc/connect-node'
import type * as http2 from 'node:http2'

type SessionManager = NonNullable<GrpcTransportOptions['sessionManager']>
type WriteCallback = (error?: Error | null) => void
type Chunk = { data: unknown; encoding: BufferEncoding | undefined }

// connect-node ends a request a loop pass after writing its body, and the router forwards only at END_STREAM.
export class SingleFrameRequestSessionManager implements SessionManager {
    constructor(private readonly inner: SessionManager) {}

    get authority(): string {
        return this.inner.authority
    }

    async request(
        method: string,
        path: string,
        headers: http2.OutgoingHttpHeaders,
        options: Omit<http2.ClientSessionRequestOptions, 'signal'>
    ): Promise<http2.ClientHttp2Stream> {
        const stream = await this.inner.request(method, path, headers, options)
        holdLastChunkUntilEnd(stream)
        return stream
    }

    notifyResponseByteRead(stream: http2.ClientHttp2Stream): void {
        this.inner.notifyResponseByteRead(stream)
    }
}

function holdLastChunkUntilEnd(stream: http2.ClientHttp2Stream): void {
    const write = stream.write.bind(stream) as (data: unknown, encoding?: BufferEncoding) => boolean
    const end = stream.end.bind(stream) as (...args: unknown[]) => http2.ClientHttp2Stream
    let held: Chunk | undefined

    const flushHeld = (): void => {
        if (held === undefined) {
            return
        }
        const { data, encoding } = held
        held = undefined
        if (encoding === undefined) {
            write(data)
        } else {
            write(data, encoding)
        }
    }

    stream.write = ((
        data: unknown,
        encodingOrCallback?: BufferEncoding | WriteCallback,
        callback?: WriteCallback
    ): boolean => {
        const encoding = typeof encodingOrCallback === 'string' ? encodingOrCallback : undefined
        const done = typeof encodingOrCallback === 'function' ? encodingOrCallback : callback
        flushHeld()
        held = { data, encoding }
        process.nextTick(() => done?.(null))
        return true
    }) as typeof stream.write

    stream.end = ((...args: unknown[]): http2.ClientHttp2Stream => {
        if (held === undefined) {
            return end(...args)
        }
        if (args.length > 0 && typeof args[0] !== 'function') {
            flushHeld()
            return end(...args)
        }
        const { data, encoding } = held
        held = undefined
        return encoding === undefined ? end(data, ...args) : end(data, encoding, ...args)
    }) as typeof stream.end
}
