import { defaultConfig } from '~/common/config/config'

import { scratchSchema, withPostgres } from '../environment/stack'
import { createWriterProbe } from './writer-probe'

const SCHEMA = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_writer_${process.pid}`, [])
const APPLICATION_NAME = `scenario-writer-probe-test-${process.pid}`

describe('writer probe', () => {
    beforeEach(async () => {
        await SCHEMA.create()
    })

    afterEach(async () => {
        await SCHEMA.drop()
    })

    it('commits one row per sample on its own table, loses its connection when its backend is terminated, and reconnects', async () => {
        const probe = await createWriterProbe(SCHEMA.url, APPLICATION_NAME)
        try {
            const before = await probe.sample()
            await withPostgres(
                (client) =>
                    client.query('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = $1', [
                        APPLICATION_NAME,
                    ]),
                SCHEMA.url
            )
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
