import { AddressInfo, Server, Socket, connect, createServer } from 'net'

type Connection = { client: Socket; upstream: Socket; answering: boolean }

export class StallingValkeyProxy {
    private server: Server | undefined
    private readonly connections = new Set<Connection>()
    private newConnectionsAnswer = true

    constructor(private readonly target: { host: string; port: number }) {}

    async start(): Promise<number> {
        this.server = createServer((client) => {
            const connection: Connection = {
                client,
                upstream: connect(this.target.port, this.target.host),
                answering: this.newConnectionsAnswer,
            }
            this.connections.add(connection)
            client.on('error', () => undefined)
            connection.upstream.on('error', () => undefined)
            client.on('data', (chunk) => connection.upstream.write(chunk))
            connection.upstream.on('data', (chunk) => {
                if (connection.answering) {
                    client.write(chunk)
                }
            })
            client.on('close', () => {
                connection.upstream.destroy()
                this.connections.delete(connection)
            })
        })
        await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve))
        return (this.server!.address() as AddressInfo).port
    }

    get openConnections(): number {
        return this.connections.size
    }

    stopAnsweringOpenConnections(): void {
        this.connections.forEach((connection) => {
            connection.answering = false
        })
    }

    stopAnswering(): void {
        this.newConnectionsAnswer = false
        this.stopAnsweringOpenConnections()
    }

    answerNewConnections(): void {
        this.newConnectionsAnswer = true
    }

    stop(): void {
        this.connections.forEach(({ client, upstream }) => {
            upstream.destroy()
            client.destroy()
        })
        this.server?.close()
    }

    // For a pool whose clients reconnect: a closed socket sends its ioredis client into a reconnect loop for the
    // rest of the Jest worker, and RedisV2 has no close to stop it, so the client sockets stay open but silent.
    stopLeavingClientsSilent(): void {
        this.stopAnswering()
        this.connections.forEach(({ client, upstream }) => {
            upstream.destroy()
            client.unref()
        })
        this.server?.close()
        this.server?.unref()
    }
}
