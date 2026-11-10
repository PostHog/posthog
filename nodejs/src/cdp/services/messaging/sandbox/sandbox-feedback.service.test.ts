import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import { createSign, generateKeyPairSync } from 'node:crypto'
import { register } from 'prom-client'
import supertest from 'supertest'
import express from 'ultimate-express'

import { CdpApi } from '~/cdp/cdp-api'
import { setupExpressApp } from '~/common/api/router'
import { KAFKA_APP_METRICS_2 } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchResponse } from '~/common/utils/request'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

const mockAnalytics = { received: [] as Record<string, any>[], failing: false }

jest.mock('posthog-node', () => ({
    PostHog: class {
        capture(message: Record<string, any>): void {
            if (mockAnalytics.failing) {
                throw new Error('analytics unreachable')
            }
            mockAnalytics.received.push(message)
        }
        captureException(): void {}
        disable(): Promise<void> {
            return Promise.resolve()
        }
        register(): Promise<void> {
            return Promise.resolve()
        }
        isFeatureEnabled(): Promise<boolean> {
            return Promise.resolve(false)
        }
        flush(): Promise<void> {
            return Promise.resolve()
        }
        shutdown(): Promise<void> {
            return Promise.resolve()
        }
    },
}))

// jest.setup.ts loads the config before this file runs, with no POSTHOG_API_KEY, so the analytics
// client would be null. Loading the module again in an isolated registry builds it with a key.
jest.mock('~/common/utils/posthog', () => {
    process.env.POSTHOG_API_KEY = 'phc_sandbox_feedback_test'
    let analyticsModule: unknown
    jest.isolateModules(() => {
        analyticsModule = jest.requireActual('~/common/utils/posthog')
    })
    return analyticsModule
})

const TOPIC_ARN = 'arn:aws:sns:us-east-1:123456789012:workflows-sandbox-feedback'
const FROM_ADDRESS = 'sandbox@mail.example.com'
const RECIPIENT = 'member@example.com'
const FLOW_ID = '0190a7f2-1c2b-7d3e-8f40-5a6b7c8d9e0f'
const RUN_ID = '0190a7f2-1c2b-7d3e-8f40-000000000001'
const ACTION_ID = 'action_email_sandbox_1'
const CERT_URL = 'https://sns.us-east-1.amazonaws.com/SimpleNotificationService-test.pem'

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
const publicKeyPem = publicKey.export({ type: 'spki', format: 'pem' }).toString()

const SIGNED_FIELDS: Record<string, string[]> = {
    Notification: ['Message', 'MessageId', 'Timestamp', 'TopicArn', 'Type'],
    SubscriptionConfirmation: ['Message', 'MessageId', 'SubscribeURL', 'Timestamp', 'Token', 'TopicArn', 'Type'],
}

const signed = (envelope: Record<string, string>): Record<string, string> => {
    const stringToSign = SIGNED_FIELDS[envelope.Type].map((k) => `${k}\n${envelope[k]}`).join('\n') + '\n'
    const signer = createSign('RSA-SHA1')
    signer.update(stringToSign, 'utf8')
    return { ...envelope, Signature: signer.sign(privateKey, 'base64') }
}

const secondsFromNow = (seconds: number): string => new Date(Date.now() + seconds * 1000).toISOString()

const sandboxTags = (teamId: number, overrides: Record<string, string[] | undefined> = {}): Record<string, string[]> =>
    Object.fromEntries(
        Object.entries({
            ph_sbx_team: [String(teamId)],
            ph_sbx_flow: [FLOW_ID],
            ph_sbx_run: [RUN_ID],
            ph_sbx_action: [ACTION_ID],
            ph_sbx_version: ['3'],
            ph_sbx_test: ['false'],
            ...overrides,
        }).filter((entry): entry is [string, string[]] => entry[1] !== undefined)
    )

const sesRecord = (teamId: number, event: Record<string, unknown>, mail: Record<string, unknown> = {}) => ({
    mail: {
        timestamp: secondsFromNow(-120),
        source: `"Example via PostHog" <${FROM_ADDRESS}>`,
        messageId: 'ses-message-id',
        destination: [RECIPIENT],
        tags: sandboxTags(teamId),
        ...mail,
    },
    ...event,
})

const notification = (record: unknown, topicArn = TOPIC_ARN, certUrl = CERT_URL): string =>
    JSON.stringify(
        signed({
            Type: 'Notification',
            MessageId: 'sns-message-id',
            TopicArn: topicArn,
            Message: JSON.stringify(record),
            Timestamp: secondsFromNow(-60),
            SignatureVersion: '1',
            Signature: '',
            SigningCertURL: certUrl,
        })
    )

const permanentBounce = (address = RECIPIENT) => ({
    eventType: 'Bounce',
    bounce: {
        bounceType: 'Permanent',
        bounceSubType: 'General',
        bouncedRecipients: [{ emailAddress: address, status: '5.1.1', diagnosticCode: 'smtp; 550 5.1.1 user unknown' }],
        timestamp: secondsFromNow(-60),
    },
})

const transientBounce = () => ({
    eventType: 'Bounce',
    bounce: {
        bounceType: 'Transient',
        bouncedRecipients: [{ emailAddress: RECIPIENT, diagnosticCode: 'smtp; 452 mailbox full' }],
        timestamp: secondsFromNow(-60),
    },
})

const complaint = (feedbackType = 'abuse') => ({
    eventType: 'Complaint',
    complaint: {
        complainedRecipients: [{ emailAddress: RECIPIENT }],
        complaintFeedbackType: feedbackType,
        timestamp: secondsFromNow(-60),
    },
})

const delivery = () => ({
    eventType: 'Delivery',
    delivery: { timestamp: secondsFromNow(1), recipients: [RECIPIENT] },
})

const fetchResponse = (status: number): FetchResponse =>
    ({
        status,
        headers: {},
        json: () => Promise.resolve({}),
        text: () => Promise.resolve(''),
        dump: () => Promise.resolve(),
    }) as FetchResponse

const counterValue = async (name: string, labels: Record<string, string>): Promise<number> => {
    const metric = await register.getSingleMetric(name)?.get()
    return metric?.values.find((v) => Object.entries(labels).every(([k, value]) => v.labels[k] === value))?.value ?? 0
}

describe('POST /public/m/ses_sandbox_webhook', () => {
    let hub: Hub
    let team: Team
    let server: Server | undefined
    let app: express.Application

    const startApi = (config: { allowed?: string; from?: string } = {}): void => {
        server?.close()
        hub.SES_SANDBOX_ALLOWED_SNS_TOPIC_ARNS = config.allowed ?? TOPIC_ARN
        hub.SES_SANDBOX_FROM_ADDRESS = config.from ?? FROM_ADDRESS
        const api = new CdpApi(hub, createCdpConsumerDeps(hub), {
            hogQueue: createMockJobQueue(),
            hogflowQueue: createMockJobQueue(),
        })
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    }

    const post = (body: string): supertest.Test =>
        supertest(app).post('/public/m/ses_sandbox_webhook').set('Content-Type', 'text/plain').send(body)

    const suppressionRows = async (): Promise<Record<string, unknown>[]> =>
        (
            await hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT identifier, source, suppressed, transient_bounce_count
                 FROM posthog_messagesuppression WHERE team_id = $1 ORDER BY identifier`,
                [team.id],
                'test-read-sandbox-suppression'
            )
        ).rows

    const globalHardBounces = async (): Promise<string[]> =>
        (
            await hub.postgres.query<{ email: string }>(
                PostgresUse.COMMON_READ,
                `SELECT email FROM posthog_emailhardbounce WHERE email = $1`,
                [RECIPIENT],
                'test-read-sandbox-global-bounces'
            )
        ).rows.map((row) => row.email)

    const sandboxMetrics = (): Record<string, any>[] =>
        mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
            .map((message) => message.value as Record<string, any>)
            .filter((value) => String(value.metric_name).startsWith('email_sandbox_'))

    const capturedEvents = (): Record<string, any>[] =>
        mockAnalytics.received.filter((message) => String(message.event).startsWith('workflows sandbox email'))

    const capturedEvent = (event: string, properties: Record<string, any>): Record<string, any> => ({
        distinctId: team.uuid,
        event,
        properties: { team: team.uuid, ...properties },
        groups: expect.objectContaining({ project: team.uuid, organization: team.organization_id }),
    })

    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM posthog_emailhardbounce WHERE email = $1`,
            [RECIPIENT],
            'test-reset-sandbox-global-bounces'
        )
        mockProducerObserver.resetKafkaProducer()
        mockAnalytics.received.length = 0
        mockAnalytics.failing = false
        mockFetch.mockReset()
        mockFetch.mockImplementation((url) =>
            Promise.resolve({
                status: 200,
                headers: {},
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(url.endsWith('.pem') ? publicKeyPem : ''),
            } as FetchResponse)
        )
        startApi()
    })

    afterEach(async () => {
        server?.close()
        server = undefined
        await closeHub(hub)
    })

    describe('request authentication', () => {
        it.each([
            ['no topic allowlist', { allowed: '' }],
            ['a blank topic allowlist', { allowed: ' , ' }],
            ['no sandbox From address', { from: '' }],
        ])('refuses every request with %s', async (_label, config) => {
            startApi(config)

            const res = await post(notification(sesRecord(team.id, complaint())))

            expect(res.status).toBe(503)
            expect(await suppressionRows()).toEqual([])
        })

        it.each([
            [
                'an unsigned raw delivery',
                () => JSON.stringify([sesRecord(team.id, complaint())]),
                403,
                'Unsigned raw delivery not allowed',
            ],
            [
                'a forged signature',
                () =>
                    JSON.stringify({
                        ...parseJSON(notification(sesRecord(team.id, complaint()))),
                        Signature: 'Zm9yZ2Vk',
                    }),
                403,
                'Invalid SNS signature',
            ],
            [
                'a topic outside the allowlist',
                () => notification(sesRecord(team.id, complaint()), 'arn:aws:sns:us-east-1:999999999999:other'),
                403,
                'SNS TopicArn not allowed',
            ],
            ['a body that is not JSON', () => 'not json', 400, 'Invalid SNS message'],
            [
                'a body that is neither an envelope nor SES records',
                () => '{"hello":"world"}',
                400,
                'Invalid SNS message',
            ],
        ])('rejects %s', async (_label, body, status, message) => {
            const res = await post(body())

            expect({ status: res.status, body: res.body }).toEqual({ status, body: { message } })
            expect(await suppressionRows()).toEqual([])
        })

        it.each([
            ['plain HTTP', 'http://sns.us-east-1.amazonaws.com/SimpleNotificationService-test.pem'],
            ['a host outside AWS', 'https://attacker.example.com/SimpleNotificationService-test.pem'],
            ['an AWS-looking host prefix', 'https://sns.us-east-1.amazonaws.com.attacker.example/cert.pem'],
            ['a path that is not a PEM file', 'https://sns.us-east-1.amazonaws.com/cert.txt'],
        ])('rejects a signing certificate served over %s without fetching it', async (_label, certUrl) => {
            const res = await post(notification(sesRecord(team.id, complaint()), TOPIC_ARN, certUrl))

            expect({ status: res.status, body: res.body }).toEqual({
                status: 403,
                body: { message: 'Invalid SNS signature' },
            })
            expect(mockFetch).not.toHaveBeenCalled()
            expect(await suppressionRows()).toEqual([])
        })

        it.each([
            ['a server error', () => mockFetch.mockResolvedValueOnce(fetchResponse(503)), 503],
            ['a network error', () => mockFetch.mockRejectedValueOnce(new Error('socket hang up')), 503],
            ['throttling', () => mockFetch.mockResolvedValueOnce(fetchResponse(429)), 503],
            ['a request timeout', () => mockFetch.mockResolvedValueOnce(fetchResponse(408)), 503],
            ['a missing certificate', () => mockFetch.mockResolvedValueOnce(fetchResponse(404)), 403],
        ])(
            'answers %s from the certificate download with %s, then verifies once it recovers',
            async (_label, fail, status) => {
                fail()
                const body = notification(sesRecord(team.id, complaint()))

                expect((await post(body)).status).toBe(status)
                expect(await suppressionRows()).toEqual([])
                expect((await post(body)).status).toBe(200)
                expect(await suppressionRows()).toMatchObject([{ identifier: RECIPIENT, source: 'COMPLAINT' }])
            }
        )

        it.each([
            ['confirms', 'https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&Token=t', 200, 1],
            ['refuses', 'https://attacker.example.com/?Action=ConfirmSubscription&Token=t', 403, 0],
        ])('%s a subscription whose SubscribeURL is %s', async (_verb, subscribeUrl, status, confirmations) => {
            const body = JSON.stringify(
                signed({
                    Type: 'SubscriptionConfirmation',
                    MessageId: 'sns-message-id',
                    Token: 't',
                    TopicArn: TOPIC_ARN,
                    Message: 'You have chosen to subscribe to the topic.',
                    SubscribeURL: subscribeUrl,
                    Timestamp: secondsFromNow(-60),
                    SignatureVersion: '1',
                    Signature: '',
                    SigningCertURL: CERT_URL,
                })
            )

            const res = await post(body)

            expect(res.status).toBe(status)
            expect(mockFetch.mock.calls.filter(([url]) => url === subscribeUrl)).toHaveLength(confirmations)
        })
    })

    describe('attribution', () => {
        it('ignores feedback about mail from another sender', async () => {
            const res = await post(notification(sesRecord(team.id, complaint(), { source: 'someone@example.com' })))

            expect(res.status).toBe(200)
            expect(await suppressionRows()).toEqual([])
        })

        it.each([
            ['no tags', () => undefined],
            ['a missing team tag', () => sandboxTags(team.id, { ph_sbx_team: undefined })],
            ['a non-numeric team tag', () => sandboxTags(team.id, { ph_sbx_team: [`${team.id}abc`] })],
            ['two team tag values', () => sandboxTags(team.id, { ph_sbx_team: [String(team.id), '43'] })],
            ['a flow tag that is not a UUID', () => sandboxTags(team.id, { ph_sbx_flow: ['not-a-uuid'] })],
            ['a run tag that is not a UUID', () => sandboxTags(team.id, { ph_sbx_run: ['run'] })],
            ['an action tag with a forbidden character', () => sandboxTags(team.id, { ph_sbx_action: ['action.1'] })],
            ['a non-numeric version tag', () => sandboxTags(team.id, { ph_sbx_version: ['v3'] })],
            ['a test tag that is not a boolean', () => sandboxTags(team.id, { ph_sbx_test: ['yes'] })],
            ['an empty parent run tag', () => sandboxTags(team.id, { ph_sbx_parent_run: [] })],
            [
                'a parent run tag with a forbidden character',
                () => sandboxTags(team.id, { ph_sbx_parent_run: ['run.1'] }),
            ],
        ])('acknowledges and counts a record with %s', async (_label, tags) => {
            const before = await counterValue('cdp_sandbox_email_feedback_unattributed_total', {
                event_type: 'Complaint',
            })

            const res = await post(notification(sesRecord(team.id, complaint(), { tags: tags() })))

            expect(res.status).toBe(200)
            expect(await suppressionRows()).toEqual([])
            expect(
                await counterValue('cdp_sandbox_email_feedback_unattributed_total', { event_type: 'Complaint' })
            ).toBe(before + 1)
        })
    })

    describe('suppression and reporting', () => {
        it.each([
            {
                label: 'a permanent bounce suppresses the address for the team and globally',
                event: permanentBounce,
                rows: [{ identifier: RECIPIENT, source: 'BOUNCE', suppressed: true }],
                global: [RECIPIENT],
                metric: 'email_sandbox_bounced',
                eventName: 'workflows sandbox email bounced',
                bounceType: 'hard',
            },
            {
                label: 'a transient bounce counts toward suppression',
                event: transientBounce,
                rows: [{ identifier: RECIPIENT, source: 'BOUNCE', suppressed: false, transient_bounce_count: 1 }],
                global: [],
                metric: 'email_sandbox_bounced',
                eventName: 'workflows sandbox email bounced',
                bounceType: 'soft',
            },
            {
                label: 'a complaint suppresses the address',
                event: complaint,
                rows: [{ identifier: RECIPIENT, source: 'COMPLAINT', suppressed: true }],
                global: [],
                metric: 'email_sandbox_complained',
                eventName: 'workflows sandbox email complained',
                bounceType: undefined,
            },
        ])('$label', async ({ event, rows, global, metric, eventName, bounceType }) => {
            const res = await post(notification(sesRecord(team.id, event())))

            expect(res.status).toBe(200)
            expect(await suppressionRows()).toMatchObject(rows)
            expect(await globalHardBounces()).toEqual(global)
            await waitForExpect(() => {
                const expected = { team_id: team.id, instance_id: ACTION_ID, metric_kind: 'email', count: 1 }
                expect(sandboxMetrics()).toMatchObject([
                    { ...expected, app_source: 'hog_flow', app_source_id: FLOW_ID, metric_name: metric },
                    { ...expected, app_source: 'hog_flow_version', app_source_id: `${FLOW_ID}/3`, metric_name: metric },
                ])
                expect(capturedEvents()).toEqual([
                    capturedEvent(eventName, {
                        workflow_id: FLOW_ID,
                        action_id: ACTION_ID,
                        is_test: false,
                        ...(bounceType ? { bounce_type: bounceType } : {}),
                    }),
                ])
            })
        })

        it('a delivery resets the bounce counter and clears the global entry', async () => {
            await post(notification(sesRecord(team.id, transientBounce())))
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_emailhardbounce (email, first_bounced_at, last_bounced_at) VALUES ($1, NOW(), NOW())`,
                [RECIPIENT],
                'test-seed-sandbox-global-bounce'
            )

            const res = await post(notification(sesRecord(team.id, delivery())))

            expect(res.status).toBe(200)
            expect(await suppressionRows()).toMatchObject([{ identifier: RECIPIENT, transient_bounce_count: 0 }])
            expect(await globalHardBounces()).toEqual([])
            await waitForExpect(() => {
                expect(sandboxMetrics().map((m) => m.metric_name)).toContain('email_sandbox_delivered')
                expect(capturedEvents().map((message) => message.event)).toContain('workflows sandbox email delivered')
            })
        })

        it.each([
            ['a "not-spam" complaint', () => complaint('not-spam')],
            ['a bounce naming an address the email was not sent to', () => permanentBounce('other@example.com')],
        ])('changes nothing for %s', async (_label, event) => {
            const res = await post(notification(sesRecord(team.id, event())))

            expect(res.status).toBe(200)
            expect(await suppressionRows()).toEqual([])
            expect(await globalHardBounces()).toEqual([])
        })

        it('counts feedback from a batch-triggered run under the parent run', async () => {
            const parentRunId = '0190a7f2-1c2b-7d3e-8f40-0000000000aa'
            const tags = sandboxTags(team.id, { ph_sbx_parent_run: [parentRunId] })

            await post(notification(sesRecord(team.id, complaint(), { tags })))

            await waitForExpect(() => {
                expect(sandboxMetrics()).toMatchObject([
                    { app_source: 'hog_flow', app_source_id: parentRunId },
                    { app_source: 'hog_flow_version', app_source_id: `${FLOW_ID}/3` },
                ])
            })
        })

        it('still suppresses after a test send, and reports it as an event only', async () => {
            const tags = sandboxTags(team.id, { ph_sbx_test: ['true'] })

            const res = await post(notification(sesRecord(team.id, complaint(), { tags })))

            expect(res.status).toBe(200)
            expect(await suppressionRows()).toMatchObject([{ identifier: RECIPIENT, source: 'COMPLAINT' }])
            await waitForExpect(() => {
                expect(capturedEvents()).toEqual([
                    capturedEvent('workflows sandbox email complained', {
                        workflow_id: FLOW_ID,
                        action_id: ACTION_ID,
                        is_test: true,
                    }),
                ])
            })
            expect(sandboxMetrics()).toEqual([])
        })

        it('answers 500 when the suppression list cannot be written, so SNS retries', async () => {
            await hub.postgres.end()

            const res = await post(notification(sesRecord(team.id, complaint())))

            expect(res.status).toBe(500)
            expect(capturedEvents()).toEqual([])
        })

        it('answers 200 once the suppression write lands when Kafka and event capture fail', async () => {
            jest.mocked((mockProducer as any).producer.produce).mockImplementationOnce((...args: any[]) =>
                args[args.length - 1]?.(new Error('kafka unavailable'))
            )
            mockAnalytics.failing = true

            const res = await post(notification(sesRecord(team.id, complaint())))

            expect(res.status).toBe(200)
            expect(await suppressionRows()).toMatchObject([{ identifier: RECIPIENT, source: 'COMPLAINT' }])
        })

        it('answers 200 once the suppression write lands while Kafka and the team lookup stall', async () => {
            jest.mocked((mockProducer as any).producer.produce).mockImplementationOnce(() => undefined)
            const lockHolder = await hub.postgres.connect(PostgresUse.COMMON_WRITE)
            await lockHolder.query('BEGIN')
            await lockHolder.query('LOCK TABLE posthog_team IN ACCESS EXCLUSIVE MODE')
            try {
                const res = await post(notification(sesRecord(team.id, complaint())))

                expect(res.status).toBe(200)
                expect(await suppressionRows()).toMatchObject([{ identifier: RECIPIENT, source: 'COMPLAINT' }])
            } finally {
                await lockHolder.query('ROLLBACK')
                lockHolder.release()
            }
        })
    })
})
