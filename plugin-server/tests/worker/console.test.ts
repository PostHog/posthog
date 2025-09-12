import { mockProducerObserver } from '../helpers/mocks/producer.mock'

import { ConsoleExtension } from '@posthog/plugin-scaffold'

import { KAFKA_PLUGIN_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { Hub, PluginLogEntrySource, PluginLogEntryType } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { createConsole } from '../../src/worker/vm/extensions/console'
import { pluginConfig39 } from '../../tests/helpers/plugins'

jest.setTimeout(60000) // 60 sec timeout
jest.mock('../../src/utils/logger')

describe('console extension', () => {
    let hub: Hub

    beforeAll(async () => {
        hub = await createHub()
    })

    afterAll(async () => {
        await closeHub(hub)
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
                    const console = createConsole(hub, pluginConfig39)

                    await (console[typeMethod](...args) as unknown as Promise<void>)

                    expect(mockProducerObserver.produceSpy).toHaveBeenCalledTimes(1)
                    expect(mockProducerObserver.getParsedQueuedMessages()[0]).toEqual({
                        topic: KAFKA_PLUGIN_LOG_ENTRIES,
                        messages: [
                            {
                                key: expect.any(String),
                                value: {
                                    source: PluginLogEntrySource.Console,
                                    type,
                                    id: expect.any(String),
                                    team_id: pluginConfig39.team_id,
                                    plugin_id: pluginConfig39.plugin_id,
                                    plugin_config_id: pluginConfig39.id,
                                    timestamp: expect.any(String),
                                    message: expectedFinalMessage,
                                    instance_id: hub.instanceId.toString(),
                                },
                            },
                        ],
                    })
                })
            })
        })
    })
})
