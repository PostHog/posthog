import { Hub, LogLevel, PluginCapabilities } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { getVMPluginCapabilities } from '../../../src/worker/vm/capabilities'
import { createPluginConfigVM } from '../../../src/worker/vm/vm'
import { pluginConfig39 } from '../../helpers/plugins'

describe('getVMPluginCapabilities()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        console.info = jest.fn() as any
        console.warn = jest.fn() as any
        ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Warn })
    })

    afterAll(async () => {
        await closeHub()
    })

    function getCapabilities(indexJs: string): PluginCapabilities {
        const vm = createPluginConfigVM(hub, pluginConfig39, indexJs)
        return getVMPluginCapabilities(vm)
    }

    it('handles processEvent', () => {
        const capabilities = getCapabilities(`
            function processEvent (event, meta) { return null }
        `)
        expect(capabilities).toEqual({ jobs: [], scheduled_tasks: [], methods: ['processEvent'] })
    })

    it('handles setupPlugin', () => {
        const capabilities = getCapabilities(`
            function setupPlugin (meta) { meta.global.key = 'value' }
            function processEvent (event, meta) { event.properties={"x": 1}; return event }
        `)
        expect(capabilities).toEqual({ jobs: [], scheduled_tasks: [], methods: ['setupPlugin', 'processEvent'] })
    })

    it('handles all capabilities', () => {
        const capabilities = getCapabilities(`
            export function processEvent (event, meta) { event.properties={"x": 1}; return event }
            export function randomFunction (event, meta) { return event}
            export function onEvent (event, meta) { return event }
            export function onSnapshot (event, meta) { return event }

            export function runEveryHour(meta) {console.log('1')}

            export const jobs = {
                x: (event, meta) => console.log(event)
            }
        `)
        expect(capabilities).toEqual({
            jobs: ['x'],
            scheduled_tasks: ['runEveryHour'],
            methods: ['onEvent', 'onSnapshot', 'processEvent'],
        })
    })
})
