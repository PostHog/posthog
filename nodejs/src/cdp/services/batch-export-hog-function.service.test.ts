import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '~/cdp/_tests/examples'
import { insertHogFunction as _insertHogFunction, insertBatchExport } from '~/cdp/_tests/fixtures'
import { CdpApi } from '~/cdp/cdp-api'
import { HogFunctionType } from '~/cdp/types'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'

import { parseJSON } from '../../utils/json-parse'

describe('BatchExportHogFunctionService', () => {
    let hub: Hub
    let team: Team
    let api: CdpApi
    let app: express.Application
    let server: Server

    let batchExportId: string
    let hogFunction: HogFunctionType
    let clickhouseEvent: Record<string, any>

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        api['hogFunctionManager']['onHogFunctionsReloaded'](team.id, [item.id])
        return item
    }

    const invocationUrl = () => `/api/projects/${team.id}/hog_functions/${hogFunction.id}/batch_export_invocations`

    const postInvocation = (body: any) => supertest(app).post(invocationUrl()).send(body)

    beforeAll(async () => {
        hub = await createHub({ SITE_URL: 'http://localhost:8000' })
        team = await getFirstTeam(hub)

        api = new CdpApi(hub)
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    })

    beforeEach(async () => {
        await resetTestDatabase()
        mockFetch.mockClear()

        clickhouseEvent = {
            uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
            event: '$pageview',
            team_id: team.id,
            distinct_id: '123',
            timestamp: '2021-09-28T14:00:00Z',
            created_at: '2021-09-28T14:00:00Z',
            properties: JSON.stringify({ $lib_version: '1.0.0' }),
            elements_chain: '',
        }

        batchExportId = new UUIDT().toString()
        await insertBatchExport(hub.postgres, team.id, batchExportId)

        hogFunction = await insertHogFunction({
            name: 'test batch export hog function',
            ...HOG_EXAMPLES.simple_fetch,
            ...HOG_INPUTS_EXAMPLES.simple_fetch,
            ...HOG_FILTERS_EXAMPLES.no_filters,
            batch_export_id: batchExportId,
        })
    })

    afterAll(async () => {
        await api.stop()
        server.close()
        await closeHub(hub)
    })

    describe('request body validation', () => {
        it.each([
            ['empty body', {}, 'clickhouse_event'],
            [
                'missing event uuid',
                { clickhouse_event: { event: '$pageview', team_id: 1, distinct_id: 'x', timestamp: 't' } },
                'uuid',
            ],
            [
                'missing event name',
                {
                    clickhouse_event: {
                        uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                        team_id: 1,
                        distinct_id: 'x',
                        timestamp: 't',
                    },
                },
                'event',
            ],
        ])('rejects %s', async (_label, body, expectedField) => {
            const res = await postInvocation(body)
            expect(res.status).toEqual(400)
            expect(res.body.errors[0]).toContain('Invalid request body')
            expect(res.body.errors[0]).toContain(expectedField)
        })

        it('rejects non-string invocation_id', async () => {
            const res = await postInvocation({ clickhouse_event: clickhouseEvent, invocation_id: 12345 })
            expect(res.status).toEqual(400)
            expect(res.body.errors[0]).toContain('Invalid request body')
            expect(res.body.errors[0]).toContain('invocation_id')
        })

        it('rejects invalid uuid invocation_id', async () => {
            const res = await postInvocation({ clickhouse_event: clickhouseEvent, invocation_id: 'not-a-uuid' })
            expect(res.status).toEqual(400)
            expect(res.body.errors[0]).toContain('Invalid request body')
            expect(res.body.errors[0]).toContain('invocation_id')
        })
    })

    describe('resource lookup errors', () => {
        it('returns 404 for non-existent team', async () => {
            const res = await supertest(app)
                .post(`/api/projects/99999/hog_functions/${hogFunction.id}/batch_export_invocations`)
                .send({ clickhouse_event: clickhouseEvent })

            expect(res.status).toEqual(404)
            expect(res.body.errors[0]).toContain('99999')
        })

        it('returns 404 for non-existent hog function', async () => {
            const fakeId = new UUIDT().toString()
            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_functions/${fakeId}/batch_export_invocations`)
                .send({ clickhouse_event: clickhouseEvent })

            expect(res.status).toEqual(404)
            expect(res.body.errors[0]).toContain(fakeId)
        })

        it('returns 404 for hog function without batch_export_id', async () => {
            const nonBatchFunction = await insertHogFunction({
                name: 'non-batch hog function',
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const res = await supertest(app)
                .post(`/api/projects/${team.id}/hog_functions/${nonBatchFunction.id}/batch_export_invocations`)
                .send({ clickhouse_event: clickhouseEvent })

            expect(res.status).toEqual(404)
            expect(res.body.errors[0]).toContain(nonBatchFunction.id)
        })
    })

    describe('successful invocation', () => {
        it('executes the hog function and returns success', async () => {
            mockFetch.mockImplementationOnce(() =>
                Promise.resolve({
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                    json: () => Promise.resolve({ ok: true }),
                    text: () => Promise.resolve(JSON.stringify({ ok: true })),
                    dump: () => Promise.resolve(),
                })
            )

            const res = await postInvocation({ clickhouse_event: clickhouseEvent })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('success')
            expect(res.body.errors).toEqual([])
            expect(res.body.logs).toMatchObject([
                { level: 'info', message: expect.stringContaining('Fetch response:') },
                { level: 'debug', message: expect.stringContaining('Function completed in') },
            ])
        })

        it('uses provided invocation_id', async () => {
            mockFetch.mockImplementationOnce(() =>
                Promise.resolve({
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                    json: () => Promise.resolve({ ok: true }),
                    text: () => Promise.resolve(JSON.stringify({ ok: true })),
                    dump: () => Promise.resolve(),
                })
            )

            const invocationId = new UUIDT().toString()
            const res = await postInvocation({
                clickhouse_event: clickhouseEvent,
                invocation_id: invocationId,
            })

            expect(res.status).toEqual(200)
            expect(res.body.status).toEqual('success')
        })

        it('generates globals with source metadata', async () => {
            mockFetch.mockImplementationOnce(() =>
                Promise.resolve({
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                    json: () => Promise.resolve({ ok: true }),
                    text: () => Promise.resolve(JSON.stringify({ ok: true })),
                    dump: () => Promise.resolve(),
                })
            )

            const res = await postInvocation({ clickhouse_event: clickhouseEvent })

            expect(res.status).toEqual(200)

            expect(mockFetch).toHaveBeenCalledTimes(1)
            const fetchBody = parseJSON(mockFetch.mock.calls[0][1].body)
            expect(fetchBody).toMatchObject({
                event: expect.objectContaining({
                    uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                    event: '$pageview',
                    distinct_id: '123',
                }),
            })
        })

        it('produces monitoring metrics', async () => {
            mockFetch.mockImplementationOnce(() =>
                Promise.resolve({
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                    json: () => Promise.resolve({ ok: true }),
                    text: () => Promise.resolve(JSON.stringify({ ok: true })),
                    dump: () => Promise.resolve(),
                })
            )

            await postInvocation({ clickhouse_event: clickhouseEvent })
            await api['batchExportHogFunctionService'].stop()

            const metrics = mockProducerObserver
                .getProducedKafkaMessagesForTopic('clickhouse_app_metrics2_test')
                .map((x) => x.value) as any[]

            expect(metrics).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        metric_name: 'succeeded',
                    }),
                ])
            )
        })
    })

    describe('execution errors', () => {
        it('returns error log when fetch returns 500', async () => {
            mockFetch.mockImplementation(() =>
                Promise.resolve({
                    status: 500,
                    headers: { 'Content-Type': 'text/plain' },
                    json: () => Promise.reject(new Error('not json')),
                    text: () => Promise.resolve('Internal Server Error'),
                    dump: () => Promise.resolve(),
                })
            )

            const res = await postInvocation({ clickhouse_event: clickhouseEvent })

            expect(res.status).toEqual(200)
            expect(res.body.logs).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({
                        level: 'error',
                        message: expect.stringContaining('HTTP fetch failed'),
                    }),
                ])
            )
        })
    })
})
