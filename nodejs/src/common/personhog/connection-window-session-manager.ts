import type { GrpcTransportOptions } from '@connectrpc/connect-node'
import type * as http2 from 'node:http2'

type SessionManager = NonNullable<GrpcTransportOptions['sessionManager']>

export class ConnectionWindowSessionManager implements SessionManager {
    private readonly sized = new WeakSet<http2.ClientHttp2Session>()

    constructor(
        private readonly inner: SessionManager,
        private readonly connectionWindowBytes: number
    ) {}

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
        const session = stream.session as http2.ClientHttp2Session | undefined
        if (session && !this.sized.has(session)) {
            this.sized.add(session)
            session.setLocalWindowSize(this.connectionWindowBytes)
        }
        return stream
    }

    notifyResponseByteRead(stream: http2.ClientHttp2Stream): void {
        this.inner.notifyResponseByteRead(stream)
    }
}
