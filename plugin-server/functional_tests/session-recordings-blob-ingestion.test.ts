import fs from 'fs'
import { Consumer, Kafka, KafkaMessage, logLevel } from 'kafkajs'

import { defaultConfig } from '../src/config/config'
import { compressToString } from '../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam } from './api'
import { waitForExpect } from './expectations'

let kafka: Kafka
let organizationId: string

let dlq: KafkaMessage[]
let dlqConsumer: Consumer

beforeAll(async () => {
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS], logLevel: logLevel.NOTHING })

    dlq = []
    dlqConsumer = kafka.consumer({ groupId: 'session_recording_events_test' })
    await dlqConsumer.subscribe({ topic: 'session_recording_events_dlq' })
    await dlqConsumer.run({
        eachMessage: ({ message }) => {
            dlq.push(message)
            return Promise.resolve()
        },
    })

    organizationId = await createOrganization()
})

afterAll(async () => {
    await Promise.all([await dlqConsumer.disconnect()])
})

test.concurrent(
    `single recording event writes data to local tmp file`,
    async () => {
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()
        const sessionId = new UUIDT().toString()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$snapshot',
            properties: {
                $session_id: sessionId,
                $window_id: 'abc1234',
                $snapshot_data: { data: compressToString('yes way'), chunk_count: 1 },
            },
        })

        let tempFiles: string[] = []

        await waitForExpect(async () => {
            const files = await fs.promises.readdir(defaultConfig.SESSION_RECORDING_LOCAL_DIRECTORY)
            tempFiles = files.filter((f) => f.startsWith(`${teamId}.${sessionId}`))
            expect(tempFiles.length).toBe(1)
        })

        await waitForExpect(async () => {
            const currentFile = tempFiles[0]

            const fileContents = await fs.promises.readFile(
                `${defaultConfig.SESSION_RECORDING_LOCAL_DIRECTORY}/${currentFile}`,
                'utf8'
            )
            // check that the fileContents is equal to the string "yes way"
            expect(fileContents).toEqual('{"window_id":"abc1234","data":"yes way"}\n')
        })
    },
    20000
)
