// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import crypto from 'crypto'
import express from 'ultimate-express'

import { closeHub, createHub } from '~/utils/db/hub'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { CdpApi } from '~/cdp/cdp-api'
import supertest from 'supertest'
import { setupExpressApp } from '~/router'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { KAFKA_APP_METRICS_2 } from '~/config/kafka-topics'
import { HogFunctionType } from '~/cdp/types'
import { HogFlow } from '~/schema/hogflow'
import { Server } from 'http'
import { template as incomingWebhookTemplate } from '~/cdp/templates/_sources/webhook/incoming_webhook.template'
import { compileHog } from '../templates/compiler'

describe('SourceWebhooksConsumer', () => {
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({
            MAILJET_SECRET_KEY: 'mailjet-secret-key',
            MAILJET_PUBLIC_KEY: 'mailjet-public-key',
        })
        team = await getFirstTeam(hub)

        mockFetch.mockClear()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('handleWebhook', () => {
        // NOTE: These tests are done via the CdpApi router so we can get full coverage of the code
        let api: CdpApi
        let app: express.Application
        let hogFunction: HogFunctionType
        let server: Server

        beforeEach(async () => {
            api = new CdpApi(hub)
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})
            hogFunction = await insertHogFunction(hub.postgres, team.id, {
                hog: incomingWebhookTemplate.code,
                bytecode: await compileHog(incomingWebhookTemplate.code),
                inputs: {},
            })
        })

        afterEach(() => {
            server.close()
        })
    })
})
