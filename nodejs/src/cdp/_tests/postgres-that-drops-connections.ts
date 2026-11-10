import { AddressInfo, Socket, connect, createServer } from 'node:net'

import { PostgresRouter } from '~/common/utils/db/postgres'

export const postgresThatDropsConnections = async (
    databaseUrl: string,
    drops: (message: Buffer) => boolean
): Promise<{ postgres: PostgresRouter; close: () => Promise<void> }> => {
    const upstream = new URL(databaseUrl)
    const sockets = new Set<Socket>()
    const server = createServer((client) => {
        const database = connect(Number(upstream.port || 5432), upstream.hostname)
        for (const socket of [client, database]) {
            sockets.add(socket)
            socket.on('error', () => undefined)
            socket.on('close', () => {
                client.destroy()
                database.destroy()
            })
        }
        client.on('data', (message: Buffer) => (drops(message) ? client.destroy() : database.write(message)))
        database.pipe(client)
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const url = new URL(upstream)
    url.host = `127.0.0.1:${(server.address() as AddressInfo).port}`
    const postgres = new PostgresRouter({ DATABASE_URL: url.toString(), POSTGRES_CONNECTION_POOL_SIZE: 1 })
    return {
        postgres,
        close: async () => {
            await postgres.end()
            sockets.forEach((socket) => socket.destroy())
            await new Promise((resolve) => server.close(resolve))
        },
    }
}
