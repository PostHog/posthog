import { ProviderEdge, startProviderEdge } from '.'
import net from 'net'
import { Client, DatabaseError } from 'pg'

import { defaultConfig } from '~/common/config/config'
import { waitForExpect } from '~/tests/helpers/expectations'

import { ruleOf } from './faults'

const UPSTREAM = defaultConfig.CYCLOTRON_NODE_DATABASE_URL!
const UNDEFINED_TABLE = '42P01'
const IN_FAILED_TRANSACTION = '25P02'

const CONNECTION_LOST = 'connection lost'

const codeOf = (error: unknown): string => (error instanceof DatabaseError && error.code ? error.code : CONNECTION_LOST)

const listening = async (server: net.Server): Promise<number> => {
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    return (server.address() as net.AddressInfo).port
}

describe('the edge in front of Cyclotron', () => {
    let edge: ProviderEdge
    let client: Client

    beforeEach(async () => {
        edge = await startProviderEdge({ port: 0, pgUpstreams: [UPSTREAM] })
        client = new Client({ connectionString: edge.pgUrls[UPSTREAM] })
        await client.connect()
        await client.query('CREATE TEMP TABLE cyclotron_jobs (id int)')
    })

    afterEach(async () => {
        await client.end().catch(() => undefined)
        await edge.close()
    })

    test.each([
        ['with parameters', 'INSERT INTO cyclotron_jobs VALUES ($1)', [1]],
        ['as a simple query', 'INSERT INTO cyclotron_jobs VALUES (1)', []],
        ['after another statement in one simple query', 'SELECT 1; INSERT INTO cyclotron_jobs VALUES (1)', []],
    ])('refuses the enqueues its dose takes %s, and passes every other statement', async (_, insert, values) => {
        edge.addFault(ruleOf({ name: 'pg.enqueue_refused', dose: { count: 1 } }))

        const refused = await client.query(insert, values).then(() => 'inserted', codeOf)
        await client.query(insert, values)

        expect(refused).toBe(UNDEFINED_TABLE)
        expect((await client.query('SELECT count(*)::int AS rows FROM cyclotron_jobs')).rows).toEqual([{ rows: 1 }])
    })

    test('leaves the transaction a refused enqueue fails to Postgres', async () => {
        edge.addFault(ruleOf({ name: 'pg.enqueue_refused', dose: { count: 1 } }))

        await client.query('BEGIN')
        const refused = await client.query('INSERT INTO cyclotron_jobs VALUES ($1)', [1]).then(() => 'inserted', codeOf)
        const after = await client.query('SELECT 1').then(() => 'answered', codeOf)
        await client.query('ROLLBACK')
        await client.query('INSERT INTO cyclotron_jobs VALUES ($1)', [2])

        expect([refused, after]).toEqual([UNDEFINED_TABLE, IN_FAILED_TRANSACTION])
        expect((await client.query('SELECT id FROM cyclotron_jobs')).rows).toEqual([{ id: 2 }])
    })

    test('passes an insert into a table whose name only starts like the jobs table, and keeps the dose', async () => {
        edge.addFault(ruleOf({ name: 'pg.enqueue_refused', dose: { count: 1 } }))
        await client.query('CREATE TEMP TABLE cyclotron_jobs$shadow (id int)')

        const shadow = await client.query('INSERT INTO cyclotron_jobs$shadow VALUES (1)').then(() => 'inserted', codeOf)
        const enqueue = await client.query('INSERT INTO cyclotron_jobs VALUES (1)').then(() => 'inserted', codeOf)

        expect([shadow, enqueue]).toEqual(['inserted', UNDEFINED_TABLE])
    })

    test('counts a refusal once the client reads it, and hands the dose back when the connection closes first', async () => {
        const target = new URL(UPSTREAM)
        let cut = false
        const relay = net.createServer((inbound) => {
            const outbound = net.connect({ host: target.hostname, port: Number(target.port || 5432) })
            inbound.on('data', (chunk: Buffer) => {
                if (!cut && chunk.includes('cyclotron_jobs_refused_by_the_scenario_edge')) {
                    cut = true
                    inbound.destroy()
                    outbound.destroy()
                    return
                }
                outbound.write(chunk)
            })
            outbound.on('data', (chunk: Buffer) => inbound.write(chunk))
            for (const [socket, other] of [
                [inbound, outbound],
                [outbound, inbound],
            ]) {
                socket.on('error', () => other.destroy())
                socket.on('close', () => other.destroy())
            }
        })
        const relayed = new URL(UPSTREAM)
        relayed.hostname = '127.0.0.1'
        relayed.port = String(await listening(relay))
        const cutEdge = await startProviderEdge({ port: 0, pgUpstreams: [relayed.toString()] })
        const faultId = cutEdge.addFault(ruleOf({ name: 'pg.enqueue_refused', dose: { count: 1 } }))
        const clients: Client[] = []
        const connected = async (): Promise<Client> => {
            const next = new Client({ connectionString: cutEdge.pgUrls[relayed.toString()] })
            next.on('error', () => undefined)
            clients.push(next)
            await next.connect()
            await next.query('CREATE TEMP TABLE cyclotron_jobs (id int)')
            return next
        }
        try {
            const first = await (await connected())
                .query('INSERT INTO cyclotron_jobs VALUES (1)')
                .then(() => 'inserted', codeOf)
            const observedBeforeAnswer = cutEdge.firstAppliedAt(faultId)
            const second = await (await connected())
                .query('INSERT INTO cyclotron_jobs VALUES (1)')
                .then(() => 'inserted', codeOf)

            expect([first, observedBeforeAnswer, second]).toEqual([CONNECTION_LOST, undefined, UNDEFINED_TABLE])
            expect(cutEdge.firstAppliedAt(faultId)).toEqual(expect.any(Number))
        } finally {
            await Promise.all(clients.map((each) => each.end().catch(() => undefined)))
            await cutEdge.close()
            relay.close()
        }
    })

    test('closes a connection whose startup declares a length it cannot have, and keeps serving the others', async () => {
        const { hostname, port } = new URL(edge.pgUrls[UPSTREAM])
        const socket = net.connect({ host: hostname, port: Number(port) })
        const malformed = Buffer.alloc(8)
        malformed.writeInt32BE(4, 0)
        malformed.writeInt32BE(196608, 4)

        socket.write(malformed)
        await new Promise((resolve) => socket.once('close', resolve))

        expect((await client.query('SELECT 1 AS up')).rows).toEqual([{ up: 1 }])
    })

    test('declines encryption, and reads the plain startup a client sends after it', async () => {
        const { hostname, port, username } = new URL(edge.pgUrls[UPSTREAM])
        const socket = net.connect({ host: hostname, port: Number(port) })
        const replies: Buffer[] = []
        socket.on('data', (chunk: Buffer) => replies.push(chunk))
        const encryption = Buffer.alloc(8)
        encryption.writeInt32BE(8, 0)
        encryption.writeInt32BE(80877103, 4)
        const parameters = Buffer.from(`user\0${username}\0database\0postgres\0\0`)
        const startup = Buffer.alloc(8)
        startup.writeInt32BE(8 + parameters.length, 0)
        startup.writeInt32BE(196608, 4)

        socket.write(encryption)
        await waitForExpect(() => expect(Buffer.concat(replies).toString()).toBe('N'))
        socket.write(Buffer.concat([startup, parameters]))

        await waitForExpect(() => expect(String.fromCharCode(Buffer.concat(replies)[1])).toBe('R'))
        socket.destroy()
    })
})
