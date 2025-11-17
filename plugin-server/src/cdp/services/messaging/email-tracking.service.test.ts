import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { CdpApi } from '~/cdp/cdp-api'
import { HogFunctionType } from '~/cdp/types'
import { KAFKA_APP_METRICS_2 } from '~/config/kafka-topics'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { closeHub, createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'

import { Hub, Team } from '../../../types'
import { PIXEL_GIF } from './email-tracking.service'

describe('EmailTrackingService', () => {
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({})
        team = await getFirstTeam(hub)

        mockFetch.mockClear()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('api', () => {
        // NOTE: These tests are done via the CdpApi router so we can get full coverage of the code
        let api: CdpApi
        let app: express.Application
        let hogFunction: HogFunctionType
        const invocationId = 'invocation-id'
        let server: Server

        beforeEach(async () => {
            api = new CdpApi(hub)
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            hogFunction = await insertHogFunction(hub.postgres, team.id)
        })

        afterEach(() => {
            server.close()
        })

        describe('handleEmailTrackingRedirect', () => {
            it('should redirect to the target url and track the click metric', async () => {
                const res = await supertest(app).get(
                    `/public/m/redirect?ph_fn_id=${hogFunction.id}&ph_inv_id=${invocationId}&target=https://example.com`
                )
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com')

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(1)
                expect(messages[0].value).toMatchObject({
                    app_source: 'hog_function',
                    app_source_id: hogFunction.id,
                    instance_id: invocationId,
                    metric_kind: 'email',
                    metric_name: 'email_link_clicked',
                    team_id: team.id,
                    count: 1,
                })
            })

            it('should return 404 if the target is not provided', async () => {
                const res = await supertest(app).get(
                    `/public/m/redirect?ph_fn_id=${hogFunction.id}&ph_inv_id=${invocationId}`
                )
                expect(res.status).toBe(404)
            })

            it('should redirect even if the tracking code is invalid', async () => {
                const res = await supertest(app).get(
                    `/public/m/redirect?ph_fn_id=invalid-function-id&ph_inv_id=invalid-invocation-id&target=https://example.com`
                )
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com')

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })

        describe('email tracking pixel', () => {
            it('should return a 200 and a gif image, tracking the open metric', async () => {
                const res = await supertest(app).get(
                    `/public/m/pixel?ph_fn_id=${hogFunction.id}&ph_inv_id=${invocationId}`
                )
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(1)
                expect(messages[0].value).toMatchObject({
                    app_source: 'hog_function',
                    app_source_id: hogFunction.id,
                    instance_id: invocationId,
                    metric_kind: 'email',
                    metric_name: 'email_opened',
                    team_id: team.id,
                    count: 1,
                })
            })

            it('should return a 200 even if the tracking code is invalid', async () => {
                const res = await supertest(app).get(`/public/m/pixel?ph_fn_id=${new UUIDT()}&ph_inv_id=${new UUIDT()}`)
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })
    })
})
