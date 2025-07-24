import '../../tests/helpers/mocks/producer.mock'

import express from 'express'
import supertest from 'supertest'

import { setupExpressApp } from '~/router'
import { waitForExpect } from '~/tests/helpers/expectations'

import { resetTestDatabase } from '../../tests/helpers/sql'
import { Hub } from '../types'
import { closeHub, createHub } from '../utils/db/hub'
import { ServerCommands } from './commands'

describe('Commands API', () => {
    let hub: Hub
    let app: express.Application
    let service: ServerCommands

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()

        service = new ServerCommands(hub)
        app = setupExpressApp()
        app.use('/', service.router())
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    it('succeeds with valid command', async () => {
        const res = await supertest(app).post(`/api/commands`).send({ command: 'reload-plugins', message: {} })
        expect(res.status).toEqual(200)
    })

    describe('command triggers', () => {
        beforeEach(() => {
            jest.spyOn(service as any, 'reloadPlugins')
            jest.spyOn(service as any, 'populatePluginCapabilities')
        })

        it.each([
            ['reload-plugins', 'reloadPlugins', {}],
            ['populate-plugin-capabilities', 'populatePluginCapabilities', { pluginId: '123' }],
        ])('triggers the appropriate pubsub message', async (command, method, message) => {
            await supertest(app).post(`/api/commands`).send({ command, message })
            // Slight delay as it is received via the pubsub
            await waitForExpect(() => {
                expect((service as any)[method]).toHaveBeenCalledWith(message)
            }, 100)
        })
    })
})
