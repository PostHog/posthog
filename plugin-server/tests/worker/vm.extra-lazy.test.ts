import fetch from 'node-fetch'

import { Hub, PluginTaskType } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { pluginDigest } from '../../src/utils/utils'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { plugin60, pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

describe('VMs are extra lazy 💤', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub()
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    test('VM without tasks delays setup until necessary', async () => {
        const indexJs = `
        export async function setupPlugin () {
            await fetch('https://onevent.com/')
        }

        export async function onEvent () {

        }
    `
        await resetTestDatabase(indexJs)
        const pluginConfig = { ...pluginConfig39, plugin: plugin60 }
        const lazyVm = new LazyPluginVM(hub, pluginConfig)
        pluginConfig.instance = lazyVm
        jest.spyOn(lazyVm, 'setupPluginIfNeeded')
        await lazyVm.initialize!(indexJs, pluginDigest(plugin60))

        expect(lazyVm.ready).toEqual(false)
        expect(lazyVm.setupPluginIfNeeded).not.toHaveBeenCalled()
        expect(fetch).not.toHaveBeenCalled()

        await lazyVm.getPluginMethod('onEvent')
        expect(lazyVm.ready).toEqual(true)
        expect(lazyVm.setupPluginIfNeeded).toHaveBeenCalled()
        expect(fetch).toHaveBeenCalledWith('https://onevent.com/', undefined)
    })
})
