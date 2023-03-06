import { Hub, PluginError } from '../src/types'
import { createHub } from '../src/utils/db/hub'
import {
    disablePlugin,
    getPluginAttachmentRows,
    getPluginConfigRows,
    getPluginRows,
    setError,
} from '../src/utils/db/sql'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20_000)
jest.mock('../src/utils/status')

describe('sql', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let organizationId: string
    let teamId: number
    let pluginConfigId: number
    let pluginAttachmentId: number
    let pluginId: number

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    beforeEach(async () => {
        ;({ organizationId, teamId, pluginId, pluginConfigId, pluginAttachmentId } = await resetTestDatabase(
            `const processEvent = event => event`
        ))
    })

    afterAll(async () => {
        await closeHub()
    })

    test('getPluginAttachmentRows', async () => {
        const rowsExpected = [
            {
                content_type: 'application/octet-stream',
                contents: Buffer.from([116, 101, 115, 116]),
                file_name: 'test.txt',
                file_size: 4,
                id: pluginAttachmentId,
                key: 'maxmindMmdb',
                plugin_config_id: pluginConfigId,
                team_id: teamId,
            },
        ]

        const rows1 = (await getPluginAttachmentRows(hub)).filter((x) => x.team_id === teamId)
        expect(rows1).toEqual(rowsExpected)
        await hub.db.postgresQuery(`update posthog_team set plugins_opt_in='f' where id = $1`, [teamId], 'testTag')
        const rows2 = (await getPluginAttachmentRows(hub)).filter((x) => x.team_id === teamId)
        expect(rows2).toEqual(rowsExpected)
    })

    test('getPluginConfigRows', async () => {
        const expectedRow = {
            config: {
                localhostIP: '94.224.212.175',
            },
            enabled: true,
            has_error: false,
            id: pluginConfigId,
            order: 0,
            plugin_id: pluginId,
            team_id: teamId,
            created_at: expect.anything(),
            updated_at: expect.anything(),
        }

        const rows1 = (await getPluginConfigRows(hub)).filter((x) => x.id === pluginConfigId)
        expect(rows1).toEqual([expectedRow])

        await hub.db.postgresQuery("update posthog_team set plugins_opt_in='f' where id = $1", [teamId], 'testTag')
        const pluginError: PluginError = { message: 'error happened', time: 'now' }
        await setError(hub, pluginError, { ...pluginConfig39, id: pluginConfigId, plugin_id: pluginId })

        const rows2 = (await getPluginConfigRows(hub)).filter((x) => x.id === pluginConfigId)
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
                id: pluginId,
                is_global: false,
                is_stateless: false,
                organization_id: organizationId,
                log_level: null,
                name: expect.any(String),
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

        const rows1 = (await getPluginRows(hub)).filter((x) => x.organization_id === organizationId)
        expect(rows1).toEqual(rowsExpected)
        await hub.db.postgresQuery("update posthog_team set plugins_opt_in='f' where id = $1", [teamId], 'testTag')
        const rows2 = (await getPluginRows(hub)).filter((x) => x.organization_id === organizationId)
        expect(rows2).toEqual(rowsExpected)
    })

    test('setError', async () => {
        hub.db.postgresQuery = jest.fn() as any

        await setError(hub, null, { ...pluginConfig39, id: pluginConfigId, plugin_id: pluginId })
        expect(hub.db.postgresQuery).toHaveBeenCalledWith(
            'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
            [null, pluginConfigId],
            'updatePluginConfigError'
        )

        const pluginError: PluginError = { message: 'error happened', time: 'now' }
        await setError(hub, pluginError, { ...pluginConfig39, id: pluginConfigId, plugin_id: pluginId })
        expect(hub.db.postgresQuery).toHaveBeenCalledWith(
            'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
            [pluginError, pluginConfigId],
            'updatePluginConfigError'
        )
    })

    describe('disablePlugin', () => {
        test('disablePlugin disables a plugin', async () => {
            const redis = await hub.db.redisPool.acquire()
            const rowsBefore = (await getPluginConfigRows(hub)).filter((x) => x.id === pluginConfigId)
            expect(rowsBefore[0].plugin_id).toEqual(pluginId)
            expect(rowsBefore[0].enabled).toEqual(true)

            const receivedMessage = redis.subscribe(hub.PLUGINS_RELOAD_PUBSUB_CHANNEL)
            await disablePlugin(hub, pluginId)

            const rowsAfter = (await getPluginConfigRows(hub)).filter((x) => x.id === pluginConfigId)

            expect(rowsAfter).toEqual([])
            await expect(receivedMessage).resolves.toEqual(1)

            await hub.db.redisPool.release(redis)
        })
    })
})
