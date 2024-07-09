import { Hub, LogLevel, Plugin } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { INLINE_PLUGIN_MAP, syncInlinePlugins } from '../../../src/worker/vm/inline/inline'
import { resetTestDatabase } from '../../helpers/sql'

describe('Inline plugin', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        console.info = jest.fn() as any
        console.warn = jest.fn() as any
        ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log })
        await resetTestDatabase()
    })

    afterAll(async () => {
        await closeHub()
    })

    // Sync all the inline plugins, then assert that for each plugin URL, a
    // plugin exists in the database with the correct properties.
    test('syncInlinePlugins', async () => {
        await syncInlinePlugins(hub)

        const { rows }: { rows: Plugin[] } = await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            'SELECT * FROM posthog_plugin',
            undefined,
            'getPluginRows'
        )
        for (const [url, plugin] of INLINE_PLUGIN_MAP) {
            const row = rows.find((row) => row.url === url)!
            // All the inline plugin properties should align
            expect(row).not.toBeUndefined()
            expect(row.name).toEqual(plugin.description.name)
            expect(row.description).toEqual(plugin.description.description)
            expect(row.is_global).toEqual(plugin.description.is_global)
            expect(row.is_preinstalled).toEqual(plugin.description.is_preinstalled)
            expect(row.config_schema).toEqual(plugin.description.config_schema)
            expect(row.tag).toEqual(plugin.description.tag)
            expect(row.capabilities).toEqual(plugin.description.capabilities)
            expect(row.is_stateless).toEqual(plugin.description.is_stateless)
            expect(row.log_level).toEqual(plugin.description.log_level)

            // These non-inline plugin properties should be fixed across all inline plugins
            // (in true deployments some of these would not be the case, as they're leftovers from
            // before inlining, but in tests the inline plugins are always newly created)
            expect(row.plugin_type).toEqual('inline')
            expect(row.from_json).toEqual(false)
            expect(row.from_web).toEqual(false)
            expect(row.source__plugin_json).toBeUndefined()
            expect(row.source__index_ts).toBeUndefined()
            expect(row.source__frontend_tsx).toBeUndefined()
            expect(row.source__site_ts).toBeUndefined()
            expect(row.error).toBeNull()
            expect(row.organization_id).toBeNull()
            expect(row.metrics).toBeNull()
            expect(row.public_jobs).toBeNull()
        }
    })
})
