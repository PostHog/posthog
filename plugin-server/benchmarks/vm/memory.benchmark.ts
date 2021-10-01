import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { Plugin, PluginConfig, PluginConfigVMResponse } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { commonOrganizationId } from '../../tests/helpers/plugins'

jest.mock('../../src/utils/db/sql')
jest.setTimeout(600000) // 600 sec timeout

function createEvent(index: number): PluginEvent {
    return {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value', index },
    }
}

const mockPlugin: Plugin = {
    id: 4,
    organization_id: commonOrganizationId,
    plugin_type: 'custom',
    name: 'mock-plugin',
    description: 'Mock Plugin in Tests',
    url: 'http://plugins.posthog.com/mock-plugin',
    config_schema: {},
    tag: 'v1.0.0',
    archive: null,
    error: undefined,
    is_global: false,
    is_preinstalled: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
}

const mockConfig: PluginConfig = {
    id: 4,
    team_id: 2,
    plugin: mockPlugin,
    plugin_id: mockPlugin.id,
    enabled: true,
    order: 0,
    config: { configKey: 'configValue' },
    error: undefined,
    attachments: {},
    vm: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
}

test('test vm memory usage', async () => {
    const debug = false
    const numVMs = 1000
    const numEventsPerVM = 100

    const [hub, closeHub] = await createHub()
    const indexJs = `
        async function processEvent (event, meta) {
            event.event = 'changed event'
            return event
        }

        async function runEveryMinute (meta) {
            console.log('I take up space')
        }
    `

    // 10kb of maxmind plugin, uncomment if testing locally
    // const indexJs = fs.readFileSync(path.resolve(__dirname, '../../posthog-maxmind-plugin/dist/index.js')).toString()

    const getUsed = () => process.memoryUsage().heapUsed / (1024 * 1024)

    const usedAtStart = getUsed()

    let used = usedAtStart
    const vms: PluginConfigVMResponse[] = []

    for (let i = 0; i < numVMs; i++) {
        const vm = await createPluginConfigVM(hub, mockConfig, indexJs)
        vms.push(vm)

        if (debug || i === numVMs - 1) {
            const nowUsed = getUsed()
            console.log(
                `Used: ${nowUsed} MB, diff ${nowUsed - used} (${(nowUsed - usedAtStart) / (i + 1)} * ${
                    i + 1
                } used since the start)`
            )
            used = nowUsed
        }
    }

    for (let i = 0; i < numEventsPerVM; i++) {
        for (let j = 0; j < numVMs; j++) {
            await vms[j].methods.processEvent!(createEvent(i + j))
        }
        if (debug || i === numEventsPerVM - 1) {
            global?.gc?.()
            const nowUsed = getUsed()
            console.log(
                `Run ${i}. Used: ${nowUsed} MB, diff ${nowUsed - used} (${
                    nowUsed - usedAtStart
                } used since the start, ${(nowUsed - usedAtStart) / numVMs} per vm)`
            )
            used = nowUsed
        }
    }

    await closeHub()
})
