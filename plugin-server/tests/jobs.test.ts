import { gzipSync } from 'zlib'

import { defaultConfig } from '../src/config/config'
import { LOCKED_RESOURCE } from '../src/main/job-queues/job-queue-consumer'
import { JobQueueManager } from '../src/main/job-queues/job-queue-manager'
import { ServerInstance, startPluginsServer } from '../src/main/pluginsServer'
import { EnqueuedJob, Hub, LogLevel, PluginsServerConfig } from '../src/types'
import { createHub } from '../src/utils/db/hub'
import { killProcess } from '../src/utils/kill'
import { delay } from '../src/utils/utils'
import { makePiscina } from '../src/worker/piscina'
import { createPosthog, DummyPostHog } from '../src/worker/vm/extensions/posthog'
import { writeToFile } from '../src/worker/vm/extensions/test-utils'
import { resetGraphileSchema } from './helpers/graphile'
import { pluginConfig39 } from './helpers/plugins'
import { resetTestDatabase } from './helpers/sql'

const mS3WrapperInstance = {
    upload: jest.fn(),
    getObject: jest.fn(),
    deleteObject: jest.fn(),
    listObjectsV2: jest.fn(),
    mockClear: () => {
        mS3WrapperInstance.upload.mockClear()
        mS3WrapperInstance.getObject.mockClear()
        mS3WrapperInstance.deleteObject.mockClear()
        mS3WrapperInstance.listObjectsV2.mockClear()
    },
}

jest.mock('../src/utils/db/s3-wrapper', () => {
    return { S3Wrapper: jest.fn(() => mS3WrapperInstance) }
})
jest.mock('../src/utils/db/sql')
jest.mock('../src/utils/kill')
jest.setTimeout(60000) // 60 sec timeout

const { console: testConsole } = writeToFile

const testCode = `
    import { console } from 'test-utils/write-to-file'

    export const jobs = {
        logReply: (text, meta) => {
            console.log('reply', text)
        }
    }
    export async function processEvent (event, { jobs }) {
        console.log('processEvent')
        if (event.properties?.type === 'runIn') {
            jobs.logReply('runIn').runIn(1, 'second')
        } else if (event.properties?.type === 'runAt') {
            jobs.logReply('runAt').runAt(new Date())
        } else if (event.properties?.type === 'runNow') {
            jobs.logReply('runNow').runNow()
        }
        return event
    }
`

const createConfig = (config: Partial<PluginsServerConfig>): PluginsServerConfig => ({
    ...defaultConfig,
    WORKER_CONCURRENCY: 2,
    LOG_LEVEL: LogLevel.Debug,
    ...config,
})

async function waitForLogEntries(number: number) {
    const timeout = 20000
    const start = new Date().valueOf()
    while (testConsole.read().length < number) {
        await delay(200)
        if (new Date().valueOf() - start > timeout) {
            console.error(`Did not find ${number} console logs:`, testConsole.read())
            throw new Error(`Did not get ${number} console logs within ${timeout / 1000} seconds`)
        }
    }
}

describe('job queues', () => {
    let server: ServerInstance
    let posthog: DummyPostHog

    beforeEach(async () => {
        testConsole.reset()

        // reset lock in redis
        const [tempHub, closeTempHub] = await createHub()
        const redis = await tempHub.redisPool.acquire()
        await redis.del(LOCKED_RESOURCE)
        await tempHub.redisPool.release(redis)
        await closeTempHub()

        // reset test code
        await resetTestDatabase(testCode)

        // try to deflake
        await delay(100)
    })

    afterEach(async () => {
        await server?.stop()
    })

    describe('fs queue', () => {
        beforeEach(async () => {
            server = await startPluginsServer(createConfig({ JOB_QUEUES: 'fs' }), makePiscina)
            posthog = createPosthog(server.hub, pluginConfig39)
        })

        test('jobs get scheduled with runIn', async () => {
            await posthog.capture('my event', { type: 'runIn' })
            await waitForLogEntries(2)
            expect(testConsole.read()).toEqual([['processEvent'], ['reply', 'runIn']])
        })

        test('jobs get scheduled with runAt', async () => {
            await posthog.capture('my event', { type: 'runAt' })
            await waitForLogEntries(2)
            expect(testConsole.read()).toEqual([['processEvent'], ['reply', 'runAt']])
        })

        test('jobs get scheduled with runNow', async () => {
            await posthog.capture('my event', { type: 'runNow' })
            await waitForLogEntries(2)
            expect(testConsole.read()).toEqual([['processEvent'], ['reply', 'runNow']])
        })
    })

    describe('graphile', () => {
        async function initTest(
            config: Partial<PluginsServerConfig>,
            resetSchema = true
        ): Promise<PluginsServerConfig> {
            const createdConfig = createConfig(config)
            if (resetSchema) {
                await resetGraphileSchema(createdConfig)
            }
            return createdConfig
        }

        describe('jobs', () => {
            beforeEach(async () => {
                const config = await initTest({ JOB_QUEUES: 'graphile' })
                server = await startPluginsServer(config, makePiscina)
                posthog = createPosthog(server.hub, pluginConfig39)
            })

            test('graphile job queue', async () => {
                await posthog.capture('my event', { type: 'runIn' })
                await waitForLogEntries(2)
                expect(testConsole.read()).toEqual([['processEvent'], ['reply', 'runIn']])
            })

            test('polls for jobs in future', async () => {
                const DELAY = 3000 // 3s

                // return something to be picked up after a few loops (poll interval is 100ms)
                const now = Date.now()

                const job: EnqueuedJob = {
                    type: 'pluginJob',
                    payload: { key: 'value' },
                    timestamp: now + DELAY,
                    pluginConfigId: 2,
                    pluginConfigTeam: 3,
                }

                server.hub.jobQueueManager.enqueue(job)
                const consumedJob: EnqueuedJob = await new Promise((resolve, reject) => {
                    server.hub.jobQueueManager.startConsumer((consumedJob) => {
                        resolve(consumedJob[0])
                    })
                })

                expect(consumedJob).toEqual(job)
            })
        })

        describe('connection', () => {
            test('default connection', async () => {
                const config = await initTest({ JOB_QUEUES: 'graphile', JOB_QUEUE_GRAPHILE_URL: '' }, true)
                server = await startPluginsServer(config, makePiscina)
                posthog = createPosthog(server.hub, pluginConfig39)
                await posthog.capture('my event', { type: 'runIn' })
                await waitForLogEntries(2)
                expect(testConsole.read()).toEqual([['processEvent'], ['reply', 'runIn']])
            })

            describe('invalid host/domain', () => {
                // This crashes the tests as well. So... it, uhm, passes :D.
                // The crash only happens when running in Github Actions of course, so hard to debug.
                // This mode will not be activated by default, and we will not use it on cloud (yet).
                test.skip('crash', async () => {
                    const config = await initTest(
                        {
                            JOB_QUEUES: 'graphile',
                            JOB_QUEUE_GRAPHILE_URL: 'postgres://0.0.0.0:9212/database',
                            CRASH_IF_NO_PERSISTENT_JOB_QUEUE: true,
                        },
                        false
                    )
                    server = await startPluginsServer(config, makePiscina)
                    await delay(5000)
                    expect(killProcess).toHaveBeenCalled()
                })

                test('no crash', async () => {
                    const config = await initTest(
                        {
                            JOB_QUEUES: 'graphile',
                            JOB_QUEUE_GRAPHILE_URL: 'postgres://0.0.0.0:9212/database',
                            CRASH_IF_NO_PERSISTENT_JOB_QUEUE: false,
                        },
                        false
                    )
                    server = await startPluginsServer(config, makePiscina)
                    posthog = createPosthog(server.hub, pluginConfig39)
                    await posthog.capture('my event', { type: 'runIn' })
                    await waitForLogEntries(1)
                    expect(testConsole.read()).toEqual([['processEvent']])
                })
            })
        })
    })

    describe('s3 queue', () => {
        let jobQueue: JobQueueManager
        let hub: Hub
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            mS3WrapperInstance.getObject.mockReturnValueOnce({ Body: 'test' })
            ;[hub, closeHub] = await createHub(
                createConfig({
                    CRASH_IF_NO_PERSISTENT_JOB_QUEUE: true,
                    JOB_QUEUES: 's3',
                    JOB_QUEUE_S3_PREFIX: 'prefix/',
                    JOB_QUEUE_S3_BUCKET_NAME: 'bucket-name',
                    JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY: 'secret key',
                    JOB_QUEUE_S3_AWS_ACCESS_KEY: 'access key',
                    JOB_QUEUE_S3_AWS_REGION: 'region',
                })
            )
        })

        afterEach(async () => closeHub?.())

        test('calls a few functions', async () => {
            // calls a few functions to test the connection on init
            expect(mS3WrapperInstance.getObject).toBeCalledWith({
                Bucket: 'bucket-name',
                Key: expect.stringContaining('prefix/CONNTEST/'),
            })
            expect(mS3WrapperInstance.upload).toBeCalledWith({
                Body: 'test',
                Bucket: 'bucket-name',
                Key: expect.stringContaining('prefix/CONNTEST/'),
            })
            expect(mS3WrapperInstance.deleteObject).toBeCalledWith({
                Bucket: 'bucket-name',
                Key: expect.stringContaining('prefix/CONNTEST/'),
            })
            expect(mS3WrapperInstance.listObjectsV2).toBeCalledWith({
                Bucket: 'bucket-name',
                MaxKeys: 2,
                Prefix: expect.stringContaining('prefix/'),
            })

            // calls the right functions to enqueue the job
            mS3WrapperInstance.mockClear()
            const job: EnqueuedJob = {
                type: 'pluginJob',
                payload: { key: 'value' },
                timestamp: 1000000000,
                pluginConfigId: 2,
                pluginConfigTeam: 3,
            }
            await hub.jobQueueManager.enqueue(job)

            expect(mS3WrapperInstance.upload).toBeCalledWith({
                Body: gzipSync(Buffer.from(JSON.stringify(job), 'utf8')),
                Bucket: 'bucket-name',
                Key: expect.stringContaining('prefix/1970-01-12/19700112-134640.000Z-'),
            })
            expect(mS3WrapperInstance.getObject).not.toBeCalled()
            expect(mS3WrapperInstance.deleteObject).not.toBeCalled()
            expect(mS3WrapperInstance.listObjectsV2).not.toBeCalled()

            // calls the right functions to read the enqueued job
            mS3WrapperInstance.mockClear()
            mS3WrapperInstance.listObjectsV2.mockReturnValueOnce({
                Contents: [{ Key: `prefix/2020-01-01/20200101-123456.123Z-deadbeef.json.gz` }],
            })
            mS3WrapperInstance.getObject.mockReturnValueOnce({
                Body: gzipSync(Buffer.from(JSON.stringify(job), 'utf8')),
            })

            const consumedJob: EnqueuedJob = await new Promise((resolve, reject) => {
                hub.jobQueueManager.startConsumer((consumedJob) => {
                    resolve(consumedJob[0])
                })
            })
            expect(consumedJob).toEqual(job)
            await delay(10)
            expect(mS3WrapperInstance.deleteObject).toBeCalledWith({
                Bucket: 'bucket-name',
                Key: `prefix/2020-01-01/20200101-123456.123Z-deadbeef.json.gz`,
            })
        })

        test('polls for new jobs', async () => {
            const DELAY = 10000 // 10s
            // calls the right functions to read the enqueued job
            mS3WrapperInstance.mockClear()

            // return something to be picked up after a few loops (poll interval is 5s)
            const now = Date.now()
            const date = new Date(now + DELAY).toISOString()
            const [day, time] = date.split('T')
            const dayTime = `${day.split('-').join('')}-${time.split(':').join('')}`

            const job: EnqueuedJob = {
                type: 'pluginJob',
                payload: { key: 'value' },
                timestamp: now,
                pluginConfigId: 2,
                pluginConfigTeam: 3,
            }

            mS3WrapperInstance.listObjectsV2.mockReturnValue({
                Contents: [{ Key: `prefix/${day}/${dayTime}-deadbeef.json.gz` }],
            })
            mS3WrapperInstance.getObject.mockReturnValueOnce({
                Body: gzipSync(Buffer.from(JSON.stringify(job), 'utf8')),
            })

            const consumedJob: EnqueuedJob = await new Promise((resolve, reject) => {
                hub.jobQueueManager.startConsumer((consumedJob) => {
                    resolve(consumedJob[0])
                })
            })
            expect(consumedJob).toEqual(job)
            await delay(10)
            expect(mS3WrapperInstance.deleteObject).toBeCalledWith({
                Bucket: 'bucket-name',
                Key: `prefix/${day}/${dayTime}-deadbeef.json.gz`,
            })
        })
    })
})
