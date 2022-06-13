import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import { delay, UUIDT } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from './helpers/clickhouse'
import { resetKafka } from './helpers/kafka'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

const { console: testConsole } = writeToFile

jest.mock('../src/utils/status')
jest.setTimeout(60000) // 60 sec timeout

const indexJs = `
import { console as testConsole } from 'test-utils/write-to-file'

export async function processEvent (event) {
    testConsole.log('processEvent')
    event.properties.processed = 'hell yes'
    return event
}

export function onEvent (event, { global }) {
    testConsole.log('onEvent', event.event, event.properties.processed)
}
`

describe('multi-process plugin server', () => {
    let ingestionServer: ServerInstance
    let asyncServer: ServerInstance
    let posthog: DummyPostHog

    beforeAll(async () => {
        await resetKafka()
    })

    beforeEach(async () => {
        testConsole.reset()
        await resetTestDatabase(indexJs)
        await resetTestDatabaseClickhouse()
        ingestionServer = await startPluginsServer({ PLUGIN_SERVER_MODE: 'ingestion' }, makePiscina)
        asyncServer = await startPluginsServer({ PLUGIN_SERVER_MODE: 'async' }, makePiscina)
        posthog = createPosthog(ingestionServer.hub, pluginConfig39)
    })

    afterEach(async () => {
        await Promise.all([ingestionServer.stop(), asyncServer.stop()])
    })

    it('calls processEvent and onEvent properly', async () => {
        const uuid = new UUIDT().toString()

        await posthog.capture('custom event', { name: 'haha', uuid })
        await ingestionServer.hub.kafkaProducer.flush()

        await delay(5000)
        await delayUntilEventIngested(() => ingestionServer.hub.db.fetchEvents())
        await delayUntilEventIngested(() => Promise.resolve(testConsole.read()), 2)

        const events = await ingestionServer.hub.db.fetchEvents()

        expect(events.length).toBe(1)
        expect(events[0].properties).toEqual(
            expect.objectContaining({
                name: 'haha',
                processed: 'hell yes',
            })
        )
        expect(events[0].properties.processed).toEqual('hell yes')

        expect(testConsole.read()).toEqual([['processEvent'], ['onEvent', 'custom event', 'hell yes']])
    })
})
