import { createServer } from 'http'
import Redis from 'ioredis'
import { Kafka, Partitioners, Producer } from 'kafkajs'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import { UUIDT } from '../src/utils/utils'
import { capture, createAction, createOrganization, createTeam, createUser, reloadAction } from './api'

let producer: Producer
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let kafka: Kafka
let redis: Redis.Redis
let organizationId: string

beforeAll(async () => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
    })
    kafka = new Kafka({ brokers: [defaultConfig.KAFKA_HOSTS] })
    producer = kafka.producer({ createPartitioner: Partitioners.DefaultPartitioner })
    await producer.connect()
    redis = new Redis(defaultConfig.REDIS_URL)

    organizationId = await createOrganization(postgres)
})

afterAll(async () => {
    await Promise.all([producer.disconnect(), postgres.end(), redis.disconnect()])
})

test.concurrent(`webhooks: fires slack webhook`, async () => {
    // Create an action with post_to_slack enabled.
    // NOTE: I'm not 100% sure how this works i.e. what all the step
    // configuration means so there's probably a more succinct way to do
    // this.
    let webHookCalledWith: any
    const server = createServer((req, res) => {
        let body = ''
        req.on('data', (chunk) => {
            body += chunk
        })
        req.on('end', () => {
            webHookCalledWith = JSON.parse(body)
            res.writeHead(200, { 'Content-Type': 'text/plain' })
            res.end()
        })
    })

    try {
        await new Promise((resolve) => {
            server.on('listening', resolve)
            server.listen()
        })

        const distinctId = new UUIDT().toString()

        const teamId = await createTeam(postgres, organizationId, `http://localhost:${server.address()?.port}`)
        const user = await createUser(postgres, teamId, new UUIDT().toString())
        const action = await createAction(
            postgres,
            {
                team_id: teamId,
                name: 'slack',
                description: 'slack',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                deleted: false,
                post_to_slack: true,
                slack_message_format: 'default',
                created_by_id: user.id,
                is_calculating: false,
                last_calculated_at: new Date().toISOString(),
            },
            [
                {
                    name: 'slack',
                    tag_name: 'div',
                    text: 'text',
                    href: null,
                    url: 'http://localhost:8000',
                    url_matching: null,
                    event: '$autocapture',
                    properties: null,
                    selector: null,
                },
            ]
        )

        await reloadAction(redis, teamId, action.id)

        await capture(producer, teamId, distinctId, new UUIDT().toString(), '$autocapture', {
            name: 'hehe',
            uuid: new UUIDT().toString(),
            $current_url: 'http://localhost:8000',
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
        })

        for (const _ in Array.from(Array(20).keys())) {
            if (webHookCalledWith) {
                break
            }
            await new Promise((resolve) => setTimeout(resolve, 1000))
        }

        expect(webHookCalledWith).toEqual({ text: 'default' })
    } finally {
        server.close()
    }
})
