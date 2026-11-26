import { ProviderEdge, startProviderEdge } from '.'
import net from 'net'
import { Client, DatabaseError } from 'pg'

import { defaultConfig } from '~/common/config/config'
import { waitForExpect } from '~/tests/helpers/expectations'

import { ruleOf } from './faults'

const UPSTREAM = defaultConfig.CYCLOTRON_NODE_DATABASE_URL!
const UNDEFINED_TABLE = '42P01'
const IN_FAILED_TRANSACTION = '25P02'

const codeOf = (error: unknown): string | undefined => (error instanceof DatabaseError ? error.code : undefined)

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
    ])('refuses the enqueues its dose takes %s, and passes every other statement', async (_, insert, values) => {
        edge.addFault(ruleOf({ name: 'pg.enqueue_refused', dose: { count: 1 } }))

        const refused = await client.query(insert, values).then(() => undefined, codeOf)
        await client.query(insert, values)

        expect(refused).toBe(UNDEFINED_TABLE)
        expect((await client.query('SELECT count(*)::int AS rows FROM cyclotron_jobs')).rows).toEqual([{ rows: 1 }])
    })

    test('leaves the transaction a refused enqueue fails to Postgres', async () => {
        edge.addFault(ruleOf({ name: 'pg.enqueue_refused', dose: { count: 1 } }))

        await client.query('BEGIN')
        const refused = await client.query('INSERT INTO cyclotron_jobs VALUES ($1)', [1]).then(() => undefined, codeOf)
        const after = await client.query('SELECT 1').then(() => undefined, codeOf)
        await client.query('ROLLBACK')
        await client.query('INSERT INTO cyclotron_jobs VALUES ($1)', [2])

        expect([refused, after]).toEqual([UNDEFINED_TABLE, IN_FAILED_TRANSACTION])
        expect((await client.query('SELECT id FROM cyclotron_jobs')).rows).toEqual([{ id: 2 }])
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
