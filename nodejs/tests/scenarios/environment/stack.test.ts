import { defaultConfig } from '~/common/config/config'

import { withPostgres } from './stack'

const URL = defaultConfig.CYCLOTRON_NODE_DATABASE_URL!

describe('withPostgres', () => {
    it('survives the server ending its connection between queries, as a failover does', async () => {
        const ended = withPostgres(async (client) => {
            const { rows } = await client.query<{ pid: number }>('SELECT pg_backend_pid() AS pid')
            const closed = new Promise<string>((resolve) => client.once('end', () => resolve('ended')))
            await withPostgres((other) => other.query('SELECT pg_terminate_backend($1)', [rows[0].pid]), URL)
            return closed
        }, URL)

        await expect(ended).resolves.toBe('ended')
    })
})
