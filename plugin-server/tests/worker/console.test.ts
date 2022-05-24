import { ConsoleExtension } from '@posthog/plugin-scaffold'

import { Hub, PluginLogEntrySource, PluginLogEntryType } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { createConsole } from '../../src/worker/vm/extensions/console'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { resetKafka } from '../helpers/kafka'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

jest.setTimeout(60000) // 60 sec timeout

describe('console extension', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        await resetKafka()
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
    })

    afterAll(async () => {
        await closeHub()
    })

    beforeEach(async () => {
        await hub.clickhouse.querying('TRUNCATE plugin_log_entries')
    })

    Object.values(PluginLogEntryType).map((type) => {
        const method = type.toLowerCase() as keyof ConsoleExtension
        describe(`console.${method}()`, () => {
            it('stores logs based on various types of args in the database', async () => {
                const console = createConsole(hub, pluginConfig39)

                // Empty log
                await (console[method]() as unknown as Promise<void>)
                // String and number
                await (console[method]('number =', 987) as unknown as Promise<void>)
                // Object
                await (console[method]({ 1: 'ein', 2: 'zwei' }) as unknown as Promise<void>)
                // Error
                await (console[method](new Error('something')) as unknown as Promise<void>)
                // Array
                await (console[method]([99, 79]) as unknown as Promise<void>)
                await hub.kafkaProducer.flush()

                const newPluginLogEntries = await delayUntilEventIngested(() => hub.db.fetchPluginLogEntries(), 5)

                expect(newPluginLogEntries.length).toBe(5)
                expect(newPluginLogEntries).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            type: type,
                            message: '',
                            team_id: pluginConfig39.team_id,
                            plugin_config_id: pluginConfig39.id,
                            source: PluginLogEntrySource.Console,
                        }),
                        expect.objectContaining({
                            type: type,
                            message: 'number = 987',
                            team_id: pluginConfig39.team_id,
                            plugin_config_id: pluginConfig39.id,
                            source: PluginLogEntrySource.Console,
                        }),
                        expect.objectContaining({
                            type: type,
                            message: '{"1":"ein","2":"zwei"}',
                            team_id: pluginConfig39.team_id,
                            plugin_config_id: pluginConfig39.id,
                            source: PluginLogEntrySource.Console,
                        }),
                        expect.objectContaining({
                            type: type,
                            message: 'Error: something',
                            team_id: pluginConfig39.team_id,
                            plugin_config_id: pluginConfig39.id,
                            source: PluginLogEntrySource.Console,
                        }),
                        expect.objectContaining({
                            type: type,
                            message: '[99,79]',
                            team_id: pluginConfig39.team_id,
                            plugin_config_id: pluginConfig39.id,
                            source: PluginLogEntrySource.Console,
                        }),
                    ])
                )
            })
        })
    })
})
