import { Hub } from '../src/types'
import { closeHub, createHub } from '../src/utils/db/hub'
import { PostgresUse } from '../src/utils/db/postgres'
import { disablePlugin, getActivePluginRows, getPluginAttachmentRows, getPluginConfigRows } from '../src/utils/db/sql'
import { commonOrganizationId } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20_000)
jest.mock('../src/utils/logger')

describe('sql', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(`const processEvent = event => event`)
    })

    afterEach(async () => {
        await closeHub(hub)
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
            id: 39,
            order: 0,
            plugin_id: 60,
            team_id: 2,
            created_at: expect.anything(),
            updated_at: expect.anything(),
            filters: null,
        }

        const rows1 = await getPluginConfigRows(hub)
        expect(rows1).toEqual([expectedRow])
    })

    test('getActivePluginRows', async () => {
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

        const rows1 = await getActivePluginRows(hub)
        expect(rows1).toEqual(rowsExpected)
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            "update posthog_team set plugins_opt_in='f'",
            undefined,
            'testTag'
        )
        const rows2 = await getActivePluginRows(hub)
        expect(rows2).toEqual(rowsExpected)
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

            const receivedMessage = redis.subscribe('reload-plugins')
            await disablePlugin(hub, 39)

            const rowsAfter = await getPluginConfigRows(hub)

            expect(rowsAfter).toEqual([])
            await expect(receivedMessage).resolves.toEqual(1)

            await hub.db.redisPool.release(redis)
        })
    })
})
