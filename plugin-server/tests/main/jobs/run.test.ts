import { KafkaJSError } from 'kafkajs'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { createPluginConfigVM } from '../../../src/worker/vm/vm'

describe('runNow', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterAll(async () => {
        await closeHub()
    })

    test('fails on produce errors', async () => {
        // To ensure that producer errors are retried and not swallowed, we need
        // to ensure that these are bubbled up to the main consumer loop.
        const pluginConfig = {
            id: 1,
            team_id: 1,
            plugin_id: 1,
            enabled: true,
            order: 1,
            config: {},
            has_error: false,
            created_at: new Date().toString(),
            plugin: {
                id: 1,
                organization_id: 'asdf',
                plugin_type: 'source' as const,
                is_global: false,
                name: 'test',
                url: 'http://localhost:8000',
                config_schema: {},
                tag: 'test',
                description: 'test',
                from_json: false,
                to_json: '{}',
            },
        }

        const vm = createPluginConfigVM(
            hub,
            pluginConfig,
            `
            export async function onEvent(event, { jobs }) {
                await jobs.test().runNow()
            }

            export const jobs = {
                test: async () => {}
            }
        `
        )

        jest.spyOn(hub.kafkaProducer.producer, 'sendBatch').mockImplementation(() => {
            return Promise.reject(new KafkaJSError('Failed to produce'))
        })

        await expect(
            vm.methods.onEvent!({
                event: '',
                distinct_id: '',
                ip: '',
                team_id: 2,
                properties: {},
                timestamp: new Date().toString(),
                uuid: '',
            })
        ).rejects.toEqual(new KafkaJSError('Failed to produce'))
    })
})
