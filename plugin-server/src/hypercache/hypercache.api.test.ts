import { PutObjectCommand } from '@aws-sdk/client-s3'
import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { setupExpressApp } from '~/api/router'
import { resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'

import { HypercacheApi } from './hypercache.api'
import { HypercacheKey } from './services/hypercache.service'

describe('Hypercache API', () => {
    let hub: Hub
    let app: express.Application
    let server: Server
    let api: HypercacheApi

    let token = 'phc_'

    beforeAll(async () => {
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        api = new HypercacheApi(hub)
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    })

    beforeEach(async () => {
        await resetTestDatabase()

        token = 'phc_' + new UUIDT().toString()
    })

    afterAll(async () => {
        server.close()
        await closeHub(hub)
    })

    const createHypercacheEntry = async (key: HypercacheKey, token: string, only?: 'redis' | 's3') => {
        if (!only || only === 'redis') {
            const hypercache = api['hypercache']
            const redis = hypercache['redis']

            await redis.useClient({ name: 'hypercache' }, async (client) => {
                await client.set(
                    hypercache.getRedisCacheKey(key, token),
                    JSON.stringify({
                        surveys: [
                            {
                                id: '1',
                                name: 'Survey 1',
                            },
                        ],
                    })
                )
            })
        }
        if (!only || only === 's3') {
            const objectStorage = api['hypercache']['objectStorage']
            await objectStorage.s3.send(
                new PutObjectCommand({
                    Bucket: hub.OBJECT_STORAGE_BUCKET,
                    Key: api['hypercache'].getTokenCacheKey(key, token),
                    Body: JSON.stringify({
                        surveys: [
                            {
                                id: '1',
                                name: 'Survey 1',
                            },
                        ],
                    }),
                })
            )
        }
    }

    describe('/api/surveys', () => {
        it('errors if missing token', async () => {
            const res = await supertest(app).get(`/public/hypercache/api/surveys`).send()
            expect(res.status).toEqual(404)
            expect(res.body).toEqual({
                type: 'authentication_error',
                code: 'invalid_api_key',
                detail: 'Project API key invalid. You can find your project API key in your PostHog project settings.',
                attr: null,
            })
        })

        it('responds with valid entry from Hypercache if found in redis', async () => {
            await createHypercacheEntry('surveys.json', token)

            const res = await supertest(app).get(`/public/hypercache/api/surveys?token=${token}`)
            expect(res.status).toEqual(200)
            expect(res.body).toEqual({
                surveys: [
                    {
                        id: '1',
                        name: 'Survey 1',
                    },
                ],
            })
            expect(res.headers['x-posthog-cache-source']).toEqual('0')
        })

        it('responds with valid entry from S3 if not found in redis', async () => {
            await createHypercacheEntry('surveys.json', token, 's3')

            const res = await supertest(app).get(`/public/hypercache/api/surveys?token=${token}`)
            expect(res.status).toEqual(200)
            expect(res.body).toEqual({
                surveys: [
                    {
                        id: '1',
                        name: 'Survey 1',
                    },
                ],
            })
            expect(res.headers['x-posthog-cache-source']).toEqual('1')
        })
    })
})
