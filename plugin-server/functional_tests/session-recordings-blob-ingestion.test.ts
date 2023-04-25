import { GetObjectCommand, GetObjectCommandOutput, ListObjectsV2Command, S3Client } from '@aws-sdk/client-s3'
// import fs from 'fs'
// import { Consumer, Kafka, KafkaMessage, logLevel } from 'kafkajs'
import * as zlib from 'zlib'

import { defaultConfig } from '../src/config/config'
import { compressToString } from '../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import { getObjectStorage } from '../src/main/services/object_storage'
import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam } from './api'
import { waitForExpect } from './expectations'

// let kafka: Kafka
let organizationId: string

// let dlq: KafkaMessage[]
// let dlqConsumer: Consumer

let s3: S3Client

function generateVeryLongString(length = 1025) {
    return [...Array(length)].map(() => Math.random().toString(36)[2]).join('')
}

beforeAll(async () => {
    // kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })
    //
    // dlq = []
    // dlqConsumer = kafka.consumer({ groupId: 'session_recording_events_test' })
    // await dlqConsumer.subscribe({ topic: 'session_recording_events_dlq' })
    // await dlqConsumer.run({
    //     eachMessage: ({ message }) => {
    //         dlq.push(message)
    //         return Promise.resolve()
    //     },
    // })

    organizationId = await createOrganization()

    const objectStorage = getObjectStorage({
        OBJECT_STORAGE_ENDPOINT: defaultConfig.OBJECT_STORAGE_ENDPOINT,
        OBJECT_STORAGE_REGION: defaultConfig.OBJECT_STORAGE_REGION,
        OBJECT_STORAGE_ACCESS_KEY_ID: defaultConfig.OBJECT_STORAGE_ACCESS_KEY_ID,
        OBJECT_STORAGE_SECRET_ACCESS_KEY: defaultConfig.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        OBJECT_STORAGE_ENABLED: defaultConfig.OBJECT_STORAGE_ENABLED,
        OBJECT_STORAGE_BUCKET: defaultConfig.OBJECT_STORAGE_BUCKET,
    })
    if (!objectStorage) {
        throw new Error('S3 not configured')
    }
    s3 = objectStorage.s3
})

afterAll(async () => {
    // await Promise.all([await dlqConsumer.disconnect()])
})

test.concurrent(
    `single recording event writes data to local tmp file`,
    async () => {
        // const teamId = await createTeam(organizationId)
        // const distinctId = new UUIDT().toString()
        // const uuid = new UUIDT().toString()
        // const sessionId = new UUIDT().toString()
        // const veryLongString = generateVeryLongString()
        // await capture({
        //     teamId,
        //     distinctId,
        //     uuid,
        //     event: '$snapshot',
        //     properties: {
        //         $session_id: sessionId,
        //         $window_id: 'abc1234',
        //         $snapshot_data: { data: compressToString(veryLongString), chunk_count: 1 },
        //     },
        // })
        //
        // let tempFiles: string[] = []
        //
        // await waitForExpect(async () => {
        //     const files = await fs.promises.readdir(defaultConfig.SESSION_RECORDING_LOCAL_DIRECTORY)
        //     tempFiles = files.filter((f) => f.startsWith(`${teamId}.${sessionId}`))
        //     expect(tempFiles.length).toBe(1)
        // })
        //
        // await waitForExpect(async () => {
        //     const currentFile = tempFiles[0]
        //
        //     const fileContents = await fs.promises.readFile(
        //         `${defaultConfig.SESSION_RECORDING_LOCAL_DIRECTORY}/${currentFile}`,
        //         'utf8'
        //     )
        //
        //     expect(fileContents).toEqual(`{"window_id":"abc1234","data":"${veryLongString}"}\n`)
        // })
    },
    40000
)

test.skip(`multiple recording events writes compressed data to s3`, async () => {
    const teamId = await createTeam(organizationId)
    const distinctId = new UUIDT().toString()
    const sessionId = new UUIDT().toString()

    // need to send enough data to trigger the s3 upload exactly once.
    // with a buffer of 1024, an estimated gzip compression of 0.1, and 1025 default length for generateAVeryLongString
    // we need 25,000 events.
    // if any of those things change then the number of events probably needs to change too
    const captures = Array.from({ length: 25000 }).map(() => {
        return capture({
            teamId,
            distinctId,
            uuid: new UUIDT().toString(),
            event: '$snapshot',
            properties: {
                $session_id: sessionId,
                $window_id: 'abc1234',
                $snapshot_data: { data: compressToString(generateVeryLongString()), chunk_count: 1 },
            },
        })
    })
    await Promise.all(captures)

    await waitForExpect(async () => {
        const s3Files = await s3.send(
            new ListObjectsV2Command({
                Bucket: defaultConfig.OBJECT_STORAGE_BUCKET,
                Prefix: `${defaultConfig.SESSION_RECORDING_REMOTE_FOLDER}/team_id/${teamId}/session_id/${sessionId}`,
            })
        )
        expect(s3Files.Contents?.length).toBe(1)

        const s3File = s3Files.Contents?.[0]
        if (!s3File) {
            throw new Error('No s3File')
        }
        const s3FileContents: GetObjectCommandOutput = await s3.send(
            new GetObjectCommand({
                Bucket: defaultConfig.OBJECT_STORAGE_BUCKET,
                Key: s3File.Key,
            })
        )
        const fileStream = await s3FileContents.Body?.transformToByteArray()
        if (!fileStream) {
            throw new Error('No fileStream')
        }
        const text = zlib.gunzipSync(fileStream).toString().trim()
        // text contains JSON for {
        //     "window_id": "abc1234",
        //     "data": "random...string" // thousands of characters
        // }
        expect(text).toMatch(/{"window_id":"abc1234","data":"\w+"}/)
    })
}, 20000)
