import * as fetch from 'node-fetch'

import { Hub, PluginTaskType } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { pluginDigest } from '../../src/utils/utils'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { plugin60, pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

describe('VMs are extra lazy 💤', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await closeHub()
        jest.clearAllMocks()
    })
    test('VM with scheduled tasks gets setup immediately', async () => {
        const indexJs = `
        export async function runEveryMinute () {
            console.log('haha')
        }

        export async function setupPlugin () {
            await fetch('https://onevent.com/')
        }
    `
        await resetTestDatabase(indexJs)

        const pluginConfig = { ...pluginConfig39, plugin: plugin60 }
        const lazyVm = new LazyPluginVM(hub, pluginConfig)
        pluginConfig.vm = lazyVm
        jest.spyOn(lazyVm, 'setupPluginIfNeeded')
        await lazyVm.initialize!(indexJs, pluginDigest(plugin60))

        expect(lazyVm.ready).toEqual(true)
        expect(lazyVm.setupPluginIfNeeded).not.toHaveBeenCalled()
        expect(fetch).toHaveBeenCalledWith('https://onevent.com/')
    })

    test('VM with jobs gets setup immediately', async () => {
        const indexJs = `
        export async function setupPlugin () {
            await fetch('https://onevent.com/')
        }

        export const jobs = {
            test: (payload, meta) => {
                console.log(payload)
            }
        }
    `
        await resetTestDatabase(indexJs)

        const pluginConfig = { ...pluginConfig39, plugin: plugin60 }
        const lazyVm = new LazyPluginVM(hub, pluginConfig)
        pluginConfig.vm = lazyVm
        jest.spyOn(lazyVm, 'setupPluginIfNeeded')
        await lazyVm.initialize!(indexJs, pluginDigest(plugin60))

        expect(lazyVm.ready).toEqual(true)
        expect(lazyVm.setupPluginIfNeeded).not.toHaveBeenCalled()
        expect(fetch).toHaveBeenCalledWith('https://onevent.com/')
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
        pluginConfig.vm = lazyVm
        jest.spyOn(lazyVm, 'setupPluginIfNeeded')
        await lazyVm.initialize!(indexJs, pluginDigest(plugin60))

        expect(lazyVm.ready).toEqual(false)
        expect(lazyVm.setupPluginIfNeeded).not.toHaveBeenCalled()
        expect(fetch).not.toHaveBeenCalled()

        await lazyVm.getOnEvent()
        expect(lazyVm.ready).toEqual(true)
        expect(lazyVm.setupPluginIfNeeded).toHaveBeenCalled()
        expect(fetch).toHaveBeenCalledWith('https://onevent.com/')
    })

    test('getting methods and tasks returns null if plugin is in errored state', async () => {
        const indexJs = `
        export async function setupPlugin () {
            await fetch('https://onevent.com/')
        }

        export async function onEvent () {}

        export async function runEveryMinute () {}
    `
        await resetTestDatabase(indexJs)
        const pluginConfig = { ...pluginConfig39, plugin: plugin60 }
        const lazyVm = new LazyPluginVM(hub, pluginConfig)
        pluginConfig.vm = lazyVm
        jest.spyOn(lazyVm, 'setupPluginIfNeeded')
        await lazyVm.initialize!(indexJs, pluginDigest(plugin60))

        lazyVm.ready = false
        lazyVm.inErroredState = true

        const onEvent = await lazyVm.getOnEvent()
        expect(onEvent).toBeNull()
        expect(lazyVm.ready).toEqual(false)
        expect(lazyVm.setupPluginIfNeeded).toHaveBeenCalled()

        const tasks = await lazyVm.getScheduledTasks()
        expect(tasks).toEqual({})
        expect(lazyVm.ready).toEqual(false)
        expect(lazyVm.setupPluginIfNeeded).toHaveBeenCalledTimes(2)

        const task = await lazyVm.getTask('runEveryMinute', PluginTaskType.Schedule)
        expect(task).toBeNull()
        expect(lazyVm.ready).toEqual(false)
        expect(lazyVm.setupPluginIfNeeded).toHaveBeenCalledTimes(3)
    })
})
