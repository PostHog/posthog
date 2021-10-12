import { ConsoleExtension } from '@posthog/plugin-scaffold'

import { Hub, PluginLogEntryType } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { getPluginConfigRows } from '../../src/utils/db/sql'
import { createConsole } from '../../src/worker/vm/extensions/console'
import { resetTestDatabase } from '../helpers/sql'

describe('console extension', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
    })

    afterEach(async () => {
        await closeHub()
    })

    Object.values(PluginLogEntryType).map((type) => {
        const method = type.toLowerCase() as keyof ConsoleExtension
        describe(`console#${method}`, () => {
            it('leaves an empty entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(hub))[0]

                const console = createConsole(hub, pluginConfig)

                await (console[method]() as unknown as Promise<void>)

                const pluginLogEntries = await hub.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual('')
            })

            it('leaves a string + number entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(hub))[0]

                const console = createConsole(hub, pluginConfig)

                await (console[method]('number =', 987) as unknown as Promise<void>)

                const pluginLogEntries = await hub.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual('number = 987')
            })

            it('leaves an error entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(hub))[0]

                const console = createConsole(hub, pluginConfig)

                await (console[method](new Error('something')) as unknown as Promise<void>)

                const pluginLogEntries = await hub.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual('Error: something')
            })

            it('leaves an object entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(hub))[0]

                const console = createConsole(hub, pluginConfig)

                await (console[method]({ 1: 'ein', 2: 'zwei' }) as unknown as Promise<void>)

                const pluginLogEntries = await hub.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual(`{"1":"ein","2":"zwei"}`)
            })

            it('leaves an object entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(hub))[0]

                const console = createConsole(hub, pluginConfig)

                await (console[method]([99, 79]) as unknown as Promise<void>)

                const pluginLogEntries = await hub.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual(`[99,79]`)
            })
        })
    })
})
