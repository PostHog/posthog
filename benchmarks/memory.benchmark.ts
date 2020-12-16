import { createPluginConfigVM } from '../src/vm'
import { Plugin, PluginConfig, PluginConfigVMReponse } from '../src/types'
import { createServer } from '../src/server'
import { PluginEvent } from 'posthog-plugins/src/types'

jest.mock('../src/sql')

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
    plugin_type: 'custom',
    name: 'mock-plugin',
    description: 'Mock Plugin in Tests',
    url: 'http://plugins.posthog.com/mock-plugin',
    config_schema: {},
    tag: 'v1.0.0',
    archive: null,
    error: undefined,
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
}

test('test vm memory usage', async () => {
    const numVMs = 1000
    const numEventsPerVM = 100

    const [server, closeServer] = await createServer()
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
    const vms: PluginConfigVMReponse[] = []

    for (let i = 0; i < numVMs; i++) {
        const vm = await createPluginConfigVM(server, mockConfig, indexJs)
        vms.push(vm)

        const nowUsed = getUsed()
        console.log(
            `Used: ${nowUsed} MB, diff ${nowUsed - used} (${(nowUsed - usedAtStart) / (i + 1)} * ${
                i + 1
            } used since the start)`
        )
        used = nowUsed
    }

    for (let i = 0; i < numEventsPerVM; i++) {
        for (let j = 0; j < numVMs; j++) {
            await vms[j].methods.processEvent(createEvent(i + j))
        }
        global.gc()
        const nowUsed = getUsed()
        console.log(
            `Run ${i}. Used: ${nowUsed} MB, diff ${nowUsed - used} (${nowUsed - usedAtStart} used since the start, ${
                (nowUsed - usedAtStart) / numVMs
            } per vm)`
        )
        used = nowUsed
    }

    await closeServer()
})
