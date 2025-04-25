import '../../tests/helpers/mocks/producer.mock'

import express from 'express'
import supertest from 'supertest'

import { waitForExpect } from '~/tests/helpers/expectations'

import { resetTestDatabase } from '../../tests/helpers/sql'
import { Hub } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { ServerCommands } from './commands'

describe('Commands API', () => {
    let hub: Hub
    let app: express.Express
    let service: ServerCommands

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()

        service = new ServerCommands(hub)
        app = express()
        app.use(express.json())
        app.use('/', service.router())
        await service.start()
    })

    afterEach(async () => {
        await closeHub(hub)
        await service.stop()
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    it('errors if missing command', async () => {
        const res = await supertest(app).post(`/api/commands`).send({ command: 'missing', message: {} })
        expect(res.status).toEqual(400)
    })

    it('succeeds with valid command', async () => {
        const res = await supertest(app).post(`/api/commands`).send({ command: 'reload-plugins', message: {} })
        expect(res.status).toEqual(200)
    })

    describe('command triggers', () => {
        beforeEach(() => {
            for (const command of Object.keys(service.messageMap)) {
                jest.spyOn(service.messageMap, command)
            }
        })

        it.each([
            ['reload-plugins', {}],
            ['populate-plugin-capabilities', { pluginId: '123' }],
        ])('triggers the appropriate pubsub message', async (command, message) => {
            await supertest(app).post(`/api/commands`).send({ command, message })
            // Slight delay as it is received via the pubsub
            await waitForExpect(() => {
                expect(service.messageMap[command]).toHaveBeenCalledWith(JSON.stringify(message))
            }, 100)
        })
    })
})
