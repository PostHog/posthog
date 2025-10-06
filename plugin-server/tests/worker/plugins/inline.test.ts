import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, LogLevel, Plugin, PluginConfig } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import {
    INLINE_PLUGIN_MAP,
    INLINE_PLUGIN_URLS,
    constructInlinePluginInstance,
    syncInlinePlugins,
} from '../../../src/worker/vm/inline/inline'
import { VersionParts } from '../../../src/worker/vm/inline/semver-flattener'
import { PluginInstance } from '../../../src/worker/vm/lazy'
import { resetTestDatabase } from '../../helpers/sql'

describe('Inline plugin', () => {
    let hub: Hub

    beforeAll(async () => {
        console.info = jest.fn() as any
        console.warn = jest.fn() as any
        hub = await createHub({ LOG_LEVEL: LogLevel.Info })
        await resetTestDatabase()
    })

    afterAll(async () => {
        await closeHub(hub)
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
        for (const url of INLINE_PLUGIN_URLS) {
            const plugin = INLINE_PLUGIN_MAP[url]
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
        }
    })

    test('semver-flattener', async () => {
        interface SemanticVersionTestCase {
            versionString: string
            expected: VersionParts
        }

        // @ts-expect-error TODO: Make it type correctly
        const config = {
            plugin: {
                id: null,
                organization_id: null,
                plugin_type: null,
                name: null,
                is_global: null,
                url: 'inline://semver-flattener',
            },
            config: {
                properties: 'version,version2',
            },
            id: null,
            plugin_id: null,
            enabled: null,
            team_id: null,
            order: null,
            created_at: null,
        } as PluginConfig

        const instance: PluginInstance = constructInlinePluginInstance(hub, config)

        const versionExamples: SemanticVersionTestCase[] = [
            {
                versionString: '1.2.3',
                expected: { major: 1, minor: 2, patch: 3, build: undefined },
            },
            {
                versionString: '22.7',
                expected: { major: 22, minor: 7, preRelease: undefined, build: undefined },
            },
            {
                versionString: '22.7-pre-release',
                expected: { major: 22, minor: 7, patch: undefined, preRelease: 'pre-release', build: undefined },
            },
            {
                versionString: '1.0.0-alpha+001',
                expected: { major: 1, minor: 0, patch: 0, preRelease: 'alpha', build: '001' },
            },
            {
                versionString: '1.0.0+20130313144700',
                expected: { major: 1, minor: 0, patch: 0, build: '20130313144700' },
            },
            {
                versionString: '1.2.3-beta+exp.sha.5114f85',
                expected: { major: 1, minor: 2, patch: 3, preRelease: 'beta', build: 'exp.sha.5114f85' },
            },
            {
                versionString: '1.0.0+21AF26D3—-117B344092BD',
                expected: { major: 1, minor: 0, patch: 0, preRelease: undefined, build: '21AF26D3—-117B344092BD' },
            },
        ]

        const test_event: PluginEvent = {
            distinct_id: '',
            ip: null,
            site_url: '',
            team_id: 0,
            now: '',
            event: '',
            uuid: '',
            properties: {},
        }

        const method = await instance.getPluginMethod('processEvent')

        for (const { versionString, expected } of versionExamples) {
            test_event.properties!.version = versionString
            test_event.properties!.version2 = versionString
            const flattened = await method!(test_event)

            expect(flattened.properties!.version__major).toEqual(expected.major)
            expect(flattened.properties!.version__minor).toEqual(expected.minor)
            expect(flattened.properties!.version__patch).toEqual(expected.patch)
            expect(flattened.properties!.version__preRelease).toEqual(expected.preRelease)
            expect(flattened.properties!.version__build).toEqual(expected.build)

            expect(flattened.properties!.version2__major).toEqual(expected.major)
            expect(flattened.properties!.version2__minor).toEqual(expected.minor)
            expect(flattened.properties!.version2__patch).toEqual(expected.patch)
            expect(flattened.properties!.version2__preRelease).toEqual(expected.preRelease)
            expect(flattened.properties!.version2__build).toEqual(expected.build)

            // reset the event for the next iteration
            test_event.properties = {}
        }
    })
})
