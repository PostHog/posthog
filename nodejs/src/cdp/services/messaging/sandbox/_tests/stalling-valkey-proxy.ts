import { AddressInfo, Server, Socket, connect, createServer } from 'net'

export class StallingValkeyProxy {
    private server: Server | undefined
    private readonly clients = new Set<Socket>()
    private readonly upstreams = new Set<Socket>()
    private answering = true

    constructor(private readonly target: { host: string; port: number }) {}

    async start(): Promise<number> {
        this.server = createServer((client) => {
            const upstream = connect(this.target.port, this.target.host)
            this.clients.add(client)
            this.upstreams.add(upstream)
            client.on('error', () => undefined)
            upstream.on('error', () => undefined)
            client.on('data', (chunk) => upstream.write(chunk))
            upstream.on('data', (chunk) => {
                if (this.answering) {
                    client.write(chunk)
                }
            })
            client.on('close', () => upstream.destroy())
        })
        await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve))
        return (this.server!.address() as AddressInfo).port
    }

    stopAnswering(): void {
        this.answering = false
    }

    // Client sockets stay open but silent, because a closed socket sends the pool's ioredis client into a
    // reconnect loop for the rest of the Jest worker, and RedisV2 has no close to stop it.
    stop(): void {
        this.answering = false
        this.upstreams.forEach((upstream) => upstream.destroy())
        this.clients.forEach((client) => client.unref())
        this.server?.close()
        this.server?.unref()
    }
}
