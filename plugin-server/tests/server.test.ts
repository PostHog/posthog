import * as Sentry from '@sentry/node'

import { PluginServer } from '../src/server'
import { LogLevel, PluginServerMode } from '../src/types'
import { resetTestDatabase } from './helpers/sql'

jest.setTimeout(20000) // 20 sec timeout - longer indicates an issue

describe('server', () => {
    let pluginsServer: PluginServer | null = null

    beforeEach(async () => {
        jest.spyOn(Sentry, 'captureMessage')
        jest.spyOn(process, 'exit').mockImplementation()

        const testCode = `
        async function processEvent (event) {
            return event
        }
    `
        await resetTestDatabase(testCode)
    })

    afterEach(async () => {
        await pluginsServer?.stop?.()
        expect(process.exit).toHaveBeenCalledTimes(1)
        expect(process.exit).toHaveBeenCalledWith(0)
        pluginsServer = null
    })

    // Running all capabilities together takes too long in tests, so they are split up
    it('should not error on startup - ingestion', async () => {
        pluginsServer = new PluginServer({
            LOG_LEVEL: LogLevel.Debug,
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await pluginsServer.start()
    })

    it('should not error on startup - cdp', async () => {
        pluginsServer = new PluginServer({
            LOG_LEVEL: LogLevel.Debug,
            PLUGIN_SERVER_MODE: PluginServerMode.cdp_processed_events,
        })
        await pluginsServer.start()
    })

    it('should not error on startup - replay', async () => {
        pluginsServer = new PluginServer({
            LOG_LEVEL: LogLevel.Debug,
            PLUGIN_SERVER_MODE: PluginServerMode.recordings_blob_ingestion,
        })
        await pluginsServer.start()
    })
})
