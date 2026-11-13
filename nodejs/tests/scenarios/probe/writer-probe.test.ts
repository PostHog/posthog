import { defaultConfig } from '~/common/config/config'

import { scratchSchema, terminateRoleConnections, withPostgres } from '../environment/stack'
import { createWriterProbe } from './writer-probe'

const SCHEMA = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_writer_${process.pid}`, [])

describe('writer probe', () => {
    beforeEach(async () => {
        await SCHEMA.create()
    })

    afterEach(async () => {
        await SCHEMA.drop()
    })

    it('commits one row per sample on its own table, loses its connection to a drop of the roles, and reconnects', async () => {
        const probe = await createWriterProbe(SCHEMA.url)
        try {
            const before = await probe.sample()
            await terminateRoleConnections(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, 1)
            const cut = await probe.sample()
            const after = await probe.sample()

            const rows = await withPostgres(
                async (client) => (await client.query('SELECT id FROM scenario_writer_probe')).rows,
                SCHEMA.url
            )
            expect({ samples: [before, cut, after].map(({ ok, inRecovery }) => ({ ok, inRecovery })), rows }).toEqual({
                samples: [
                    { ok: true, inRecovery: false },
                    { ok: false, inRecovery: undefined },
                    { ok: true, inRecovery: false },
                ],
                rows: [{ id: '1' }, { id: '2' }],
            })
        } finally {
            await probe.end()
        }
    })

    it('records the SQLSTATE of a write the database refuses', async () => {
        const probe = await createWriterProbe(SCHEMA.url)
        try {
            await withPostgres((client) => client.query('DROP TABLE scenario_writer_probe'), SCHEMA.url)

            expect(await probe.sample()).toEqual({
                at: expect.any(Number),
                monoMs: expect.any(Number),
                ok: false,
                latencyMs: expect.any(Number),
                sqlstate: '42P01',
            })
        } finally {
            await probe.end()
        }
    })
})
