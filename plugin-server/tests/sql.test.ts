import { Hub, PluginError } from '../src/types'
import { createHub } from '../src/utils/db/hub'
import { PostgresUse } from '../src/utils/db/postgres'
import {
    disablePlugin,
    getPluginAttachmentRows,
    getPluginConfigRows,
    getPluginRows,
    setError,
} from '../src/utils/db/sql'
import { sanitizeJsonbValue } from '../src/utils/db/utils'
import { commonOrganizationId, pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20_000)
jest.mock('../src/utils/status')

describe('sql', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase(`const processEvent = event => event`)
    })

    afterEach(async () => {
        await closeHub()
    })

    test('getPluginAttachmentRows', async () => {
        const rowsExpected = [
            {
                content_type: 'application/octet-stream',
                contents: Buffer.from([116, 101, 115, 116]),
                file_name: 'test.txt',
                file_size: 4,
                id: 42666,
                key: 'maxmindMmdb',
                plugin_config_id: 39,
                team_id: 2,
            },
        ]

        const rows1 = await getPluginAttachmentRows(hub)
        expect(rows1).toEqual(rowsExpected)
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            "update posthog_team set plugins_opt_in='f'",
            undefined,
            'testTag'
        )
        const rows2 = await getPluginAttachmentRows(hub)
        expect(rows2).toEqual(rowsExpected)
    })

    test('getPluginConfigRows', async () => {
        const expectedRow = {
            config: {
                localhostIP: '94.224.212.175',
            },
            enabled: true,
            has_error: false,
            id: 39,
            order: 0,
            plugin_id: 60,
            team_id: 2,
            created_at: expect.anything(),
            updated_at: expect.anything(),
        }

        const rows1 = await getPluginConfigRows(hub)
        expect(rows1).toEqual([expectedRow])

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            "update posthog_team set plugins_opt_in='f'",
            undefined,
            'testTag'
        )
        const pluginError: PluginError = { message: 'error happened', time: 'now' }
        await setError(hub, pluginError, pluginConfig39)

        const rows2 = await getPluginConfigRows(hub)
        expect(rows2).toEqual([
            {
                ...expectedRow,
                has_error: true,
            },
        ])
    })

    test('getPluginRows', async () => {
        const rowsExpected = [
            {
                error: null,
                from_json: false,
                from_web: false,
                id: 60,
                is_global: false,
                is_stateless: false,
                organization_id: commonOrganizationId,
                log_level: null,
                name: 'test-maxmind-plugin',
                plugin_type: 'custom',
                public_jobs: null,
                source__plugin_json:
                    '{"name":"posthog-maxmind-plugin","description":"just for testing","url":"http://example.com/plugin","config":{},"main":"index.js"}',
                source__index_ts: 'const processEvent = event => event',
                source__frontend_tsx: null,
                source__site_ts: null,
                tag: '0.0.2',
                updated_at: expect.any(String),
                url: 'https://www.npmjs.com/package/posthog-maxmind-plugin',
                capabilities: {},
            },
        ]

        const rows1 = await getPluginRows(hub)
        expect(rows1).toEqual(rowsExpected)
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            "update posthog_team set plugins_opt_in='f'",
            undefined,
            'testTag'
        )
        const rows2 = await getPluginRows(hub)
        expect(rows2).toEqual(rowsExpected)
    })

    test('setError', async () => {
        hub.db.postgres.query = jest.fn() as any

        await setError(hub, null, pluginConfig39)
        expect(hub.db.postgres.query).toHaveBeenCalledWith(
            PostgresUse.COMMON_WRITE,
            'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
            [null, pluginConfig39.id],
            'updatePluginConfigError'
        )

        const pluginError: PluginError = { message: 'error happened', time: 'now' }
        await setError(hub, pluginError, pluginConfig39)
        expect(hub.db.postgres.query).toHaveBeenCalledWith(
            PostgresUse.COMMON_WRITE,
            'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
            [sanitizeJsonbValue(pluginError), pluginConfig39.id],
            'updatePluginConfigError'
        )
    })

    describe('disablePlugin', () => {
        test('disablePlugin query builds correctly', async () => {
            hub.db.postgres.query = jest.fn() as any

            await disablePlugin(hub, 39)
            expect(hub.db.postgres.query).toHaveBeenCalledWith(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_pluginconfig SET enabled='f' WHERE id=$1 AND enabled='t'`,
                [39],
                'disablePlugin'
            )
        })

        test('disablePlugin disables a plugin', async () => {
            const redis = await hub.db.redisPool.acquire()
            const rowsBefore = await getPluginConfigRows(hub)
            expect(rowsBefore[0].plugin_id).toEqual(60)
            expect(rowsBefore[0].enabled).toEqual(true)

            const receivedMessage = redis.subscribe(hub.PLUGINS_RELOAD_PUBSUB_CHANNEL)
            await disablePlugin(hub, 39)

            const rowsAfter = await getPluginConfigRows(hub)

            expect(rowsAfter).toEqual([])
            await expect(receivedMessage).resolves.toEqual(1)

            await hub.db.redisPool.release(redis)
        })
    })
})
