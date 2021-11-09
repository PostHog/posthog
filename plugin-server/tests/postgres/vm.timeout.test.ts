import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { delay } from '../../src/utils/utils'
import { createPluginConfigVM, TimeoutError } from '../../src/worker/vm/vm'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

const defaultEvent = {
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'http://localhost',
    team_id: 3,
    now: new Date().toISOString(),
    event: 'default event',
    properties: {},
}

describe('vm timeout tests', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({
            TASK_TIMEOUT: 1,
        })
    })

    afterEach(async () => {
        await closeHub()
    })

    test('while loop', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                while(1) {}
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        const date = new Date()
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(new Date().valueOf() - date.valueOf()).toBeGreaterThanOrEqual(1000)
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 3:16')
    })

    test('while loop no body', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                let i = 0
                while(1) i++;
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 4:16')
    })

    test('while loop in promise', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                await Promise.resolve().then(() => { while(1) {}; })
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 3:53')
    })

    test('do..while loop', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                do {} while (true);
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 3:16')
    })

    test('do..while loop no body', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                let i = 0;
                do i++; while (true);
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 4:16')
    })

    test('do..while loop in promise', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                await Promise.resolve().then(() => { do {} while (true); })
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 3:53')
    })

    test('for loop', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                for(let i = 0; i < 1; i--) {}
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 3:16')
    })

    test('for loop no body', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                let a = 0
                for(let i = 0; i < 1; i--) a++
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 4:16')
    })

    test('for loop in promise', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                await Promise.resolve().then(() => { for(let i = 0; i < 1; i--) {}; })
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after looping for 1 second on line 3:53')
    })

    test('small promises', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                const data = await fetch('https://www.example.com').then(response => response.json()).then(data => {
                    return data
                })

                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))

                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        const date = new Date()
        let errorMessage = undefined
        let caller = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            expect(e).toBeInstanceOf(TimeoutError)
            errorMessage = e.message
            caller = e.caller
        }
        expect(new Date().valueOf() - date.valueOf()).toBeGreaterThanOrEqual(1000)
        expect(new Date().valueOf() - date.valueOf()).toBeLessThan(4000)
        expect(errorMessage!).toEqual('Script execution timed out after promise waited for 1 second')
        expect(caller).toEqual('processEvent')
    })

    test('small promises and overriding async guard', async () => {
        const indexJs = `
            // const __asyncGuard = false
            async function processEvent (event, meta) {
                const __asyncGuard = (a) => a
                const data = await fetch('https://www.example.com').then(response => response.json()).then(data => {
                    return data
                })

                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 800))

                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        const date = new Date()
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(new Date().valueOf() - date.valueOf()).toBeGreaterThanOrEqual(1000)
        expect(new Date().valueOf() - date.valueOf()).toBeLessThan(4000)
        expect(errorMessage!).toEqual('Script execution timed out after promise waited for 1 second')
    })

    test('long promise', async () => {
        const indexJs = `
            async function processEvent (event, meta) {
                await new Promise(resolve => __jestSetTimeout(() => resolve(), 4000))
                event.properties.processed = 'yup'
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = await createPluginConfigVM(hub, pluginConfig39, indexJs)
        let errorMessage = undefined
        try {
            await vm.methods.processEvent!({ ...defaultEvent })
        } catch (e) {
            errorMessage = e.message
        }
        expect(errorMessage!).toEqual('Script execution timed out after promise waited for 1 second')
    })
})
