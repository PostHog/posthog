import { AddressInfo, Server, Socket, connect, createServer } from 'net'

type Connection = { client: Socket; upstream: Socket; answering: boolean }

export class StallingValkeyProxy {
    private server: Server | undefined
    private readonly connections = new Set<Connection>()
    private newConnectionsAnswer = true
    private refusing = false
    refusedConnections = 0

    constructor(private readonly target: { host: string; port: number }) {}

    async start(): Promise<number> {
        this.server = createServer((client) => {
            if (this.refusing) {
                this.refusedConnections++
                client.resetAndDestroy()
                return
            }
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

    refuseNewConnections(): void {
        this.refusing = true
    }

    answerNewConnections(): void {
        this.refusing = false
        this.newConnectionsAnswer = true
    }

    stop(): void {
        this.connections.forEach(({ client, upstream }) => {
            upstream.destroy()
            client.destroy()
        })
        this.server?.close()
    }

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
