import supertest from 'supertest'

import { PluginServerMode } from '~/common/config'
import { IngestionGeneralServer } from '~/servers/ingestion-general-server'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'

describe('router', () => {
    jest.retryTimes(3) // Flakey due to reliance on kafka/clickhouse
    let server: IngestionGeneralServer

    beforeAll(async () => {
        jest.spyOn(process, 'exit').mockImplementation()

        // The ingestion consumer verifies its topics exist and fails startup if they don't, which
        // silently leaves the express routes unregistered (404). Create them so startup is
        // deterministic rather than relying on ambient topics left by other tests.
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)

        server = new IngestionGeneralServer({
            PLUGIN_SERVER_MODE: PluginServerMode.ingestion_v2,
        })
        await server.start()

        server.lifecycle.httpServer = server.lifecycle.expressApp.listen(0, () => {})
    })

    afterAll(async () => {
        await server.stop()
    })

    // these should simply pass under normal conditions
    describe('health and readiness checks', () => {
        it('responds to _health', async () => {
            const res = await supertest(server.lifecycle.expressApp).get(`/_health`).send()

            expect(res.status).toEqual(200)
            expect(res.body).toMatchInlineSnapshot(`
                {
                  "checks": {
                    "analytics-main": "ok",
                    "server-commands": "ok",
                  },
                  "status": "ok",
                }
            `)
        })

        test('responds to _ready', async () => {
            const res = await supertest(server.lifecycle.expressApp).get(`/_ready`).send()

            expect(res.status).toEqual(200)
            expect(res.body).toMatchInlineSnapshot(`
                {
                  "checks": {
                    "analytics-main": "ok",
                    "server-commands": "ok",
                  },
                  "status": "ok",
                }
            `)
        })
    })
})
