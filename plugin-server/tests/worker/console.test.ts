import { ConsoleExtension } from '@posthog/plugin-scaffold'

import { KAFKA_PLUGIN_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { Hub, PluginLogEntrySource, PluginLogEntryType } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { createConsole } from '../../src/worker/vm/extensions/console'
import { pluginConfig39 } from '../../tests/helpers/plugins'

jest.setTimeout(60000) // 60 sec timeout
jest.mock('../../src/utils/status')
jest.mock('../../src/utils/db/kafka-producer-wrapper')

describe('console extension', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterAll(async () => {
        await closeHub()
    })

    Object.values(PluginLogEntryType).map((type) => {
        const typeMethod = type.toLowerCase() as keyof ConsoleExtension

        describe(`console#${typeMethod}`, () => {
            const testCases: [string, any[], string][] = [
                ['empty', [], ''],
                ['string + number', ['number =', 987], 'number = 987'],
                ['Error', [new Error('something')], 'Error: something'],
                ['object', [{ 1: 'ein', 2: 'zwei' }], `{"1":"ein","2":"zwei"}`],
                ['array', [[99, 79]], `[99,79]`],
            ]

            testCases.forEach(([description, args, expectedFinalMessage]) => {
                it(`leaves a well-formed ${description} entry in the database`, async () => {
                    const queueSingleJsonMessageSpy = jest.spyOn(hub.kafkaProducer, 'queueSingleJsonMessage')
                    const console = createConsole(hub, pluginConfig39)

                    await (console[typeMethod](...args) as unknown as Promise<void>)

                    expect(queueSingleJsonMessageSpy).toHaveBeenCalledTimes(1)
                    expect(queueSingleJsonMessageSpy).toHaveBeenCalledWith(
                        KAFKA_PLUGIN_LOG_ENTRIES,
                        expect.any(String),
                        {
                            source: PluginLogEntrySource.Console,
                            type,
                            id: expect.any(String),
                            team_id: pluginConfig39.team_id,
                            plugin_id: pluginConfig39.plugin_id,
                            plugin_config_id: pluginConfig39.id,
                            timestamp: expect.any(String),
                            message: expectedFinalMessage,
                            instance_id: hub.instanceId.toString(),
                        }
                    )
                })
            })
        })
    })
})
