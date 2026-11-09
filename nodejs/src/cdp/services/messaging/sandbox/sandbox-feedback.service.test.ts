import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import { createSign, generateKeyPairSync } from 'node:crypto'
import { register } from 'prom-client'
import supertest from 'supertest'
import express from 'ultimate-express'

import { CdpApi } from '~/cdp/cdp-api'
import { setupExpressApp } from '~/common/api/router'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchResponse } from '~/common/utils/request'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { SandboxFeedbackService } from './sandbox-feedback.service'

const TOPIC_ARN = 'arn:aws:sns:us-east-1:123456789012:workflows-sandbox-feedback'
const FROM_ADDRESS = 'sandbox@mail.example.com'
const RECIPIENT = 'member@example.com'
const FLOW_ID = '0190a7f2-1c2b-7d3e-8f40-5a6b7c8d9e0f'
const RUN_ID = '0190a7f2-1c2b-7d3e-8f40-000000000001'
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

const sandboxTags = (teamId: number, overrides: Record<string, string[] | undefined> = {}): Record<string, string[]> =>
    Object.fromEntries(
        Object.entries({
            ph_sbx_team: [String(teamId)],
            ph_sbx_flow: [FLOW_ID],
            ph_sbx_run: [RUN_ID],
            ph_sbx_action: ['action_email_sandbox_1'],
            ph_sbx_version: ['3'],
            ph_sbx_test: ['false'],
            ...overrides,
        }).filter((entry): entry is [string, string[]] => entry[1] !== undefined)
    )

const sesRecord = (teamId: number, event: Record<string, unknown>, mail: Record<string, unknown> = {}) => ({
    mail: {
        timestamp: '2026-01-01T00:00:00.000Z',
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
            Timestamp: '2026-01-01T00:00:01.000Z',
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
        timestamp: '2026-01-01T00:00:02.000Z',
    },
})

const complaint = (feedbackType = 'abuse') => ({
    eventType: 'Complaint',
    complaint: {
        complainedRecipients: [{ emailAddress: RECIPIENT }],
        complaintFeedbackType: feedbackType,
        timestamp: '2026-01-01T00:00:02.000Z',
    },
})

const fetchResponse = (status: number): FetchResponse =>
    ({ status, headers: {}, json: () => Promise.resolve({}), text: () => Promise.resolve('') }) as FetchResponse

const counterValue = async (name: string, labels: Record<string, string>): Promise<number> => {
    const metric = await register.getSingleMetric(name)?.get()
    return metric?.values.find((v) => Object.entries(labels).every(([k, value]) => v.labels[k] === value))?.value ?? 0
}

describe('SandboxFeedbackService', () => {
    const TEAM_ID = 42
    const team = { id: TEAM_ID, uuid: 'team-uuid', organization_id: 'org-uuid' } as Team

    let suppression: {
        recordDeliveries: jest.Mock
        recordHardBounces: jest.Mock
        recordGlobalHardBounces: jest.Mock
        recordTransientBounces: jest.Mock
        recordComplaints: jest.Mock
    }
    let monitoring: { queueAppMetric: jest.Mock; flush: jest.Mock }
    let capture: jest.Mock
    let service: SandboxFeedbackService

    const build = (config: { allowed?: string; from?: string } = {}): SandboxFeedbackService =>
        new SandboxFeedbackService(
            {
                SES_SANDBOX_ALLOWED_SNS_TOPIC_ARNS: config.allowed ?? TOPIC_ARN,
                SES_SANDBOX_FROM_ADDRESS: config.from ?? FROM_ADDRESS,
            },
            suppression,
            monitoring,
            { getTeam: (teamId) => Promise.resolve(teamId === TEAM_ID ? team : null) },
            capture
        )

    const writes = (): Record<string, unknown[][]> =>
        Object.fromEntries(
            Object.entries(suppression)
                .filter(([, fn]) => fn.mock.calls.length > 0)
                .map(([name, fn]) => [name, fn.mock.calls])
        )

    beforeEach(() => {
        suppression = {
            recordDeliveries: jest.fn().mockResolvedValue(undefined),
            recordHardBounces: jest.fn().mockResolvedValue(undefined),
            recordGlobalHardBounces: jest.fn().mockResolvedValue(undefined),
            recordTransientBounces: jest.fn().mockResolvedValue(undefined),
            recordComplaints: jest.fn().mockResolvedValue(undefined),
        }
        monitoring = { queueAppMetric: jest.fn(), flush: jest.fn().mockResolvedValue(undefined) }
        capture = jest.fn()
        service = build()
        mockFetch.mockReset()
        mockFetch.mockImplementation((url) =>
            Promise.resolve({
                status: 200,
                headers: {},
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(url.endsWith('.pem') ? publicKeyPem : ''),
            } as FetchResponse)
        )
    })

    describe('request authentication', () => {
        it.each([
            ['no topic allowlist', { allowed: '' }],
            ['a blank topic allowlist', { allowed: ' , ' }],
            ['no sandbox From address', { from: '' }],
        ])('refuses every request with %s', async (_label, config) => {
            const result = await build(config).handle({ body: notification(sesRecord(TEAM_ID, complaint())) })

            expect(result.status).toBe(503)
            expect(writes()).toEqual({})
        })

        it.each([
            [
                'an unsigned raw delivery',
                JSON.stringify([sesRecord(TEAM_ID, complaint())]),
                403,
                'Unsigned raw delivery not allowed',
            ],
            [
                'a forged signature',
                JSON.stringify({ ...parseJSON(notification(sesRecord(TEAM_ID, complaint()))), Signature: 'Zm9yZ2Vk' }),
                403,
                'Invalid SNS signature',
            ],
            [
                'a topic outside the allowlist',
                notification(sesRecord(TEAM_ID, complaint()), 'arn:aws:sns:us-east-1:999999999999:other'),
                403,
                'SNS TopicArn not allowed',
            ],
            ['a body that is not JSON', 'not json', 400, 'Invalid SNS message'],
            ['a body that is neither an envelope nor SES records', '{"hello":"world"}', 400, 'Invalid SNS message'],
        ])('rejects %s', async (_label, body, status, message) => {
            const result = await service.handle({ body })

            expect(result).toEqual({ status, message })
            expect(writes()).toEqual({})
        })

        it.each([
            ['plain HTTP', 'http://sns.us-east-1.amazonaws.com/SimpleNotificationService-test.pem'],
            ['a host outside AWS', 'https://attacker.example.com/SimpleNotificationService-test.pem'],
            ['an AWS-looking host prefix', 'https://sns.us-east-1.amazonaws.com.attacker.example/cert.pem'],
            ['a path that is not a PEM file', 'https://sns.us-east-1.amazonaws.com/cert.txt'],
        ])('rejects a signing certificate served over %s without fetching it', async (_label, certUrl) => {
            const result = await service.handle({
                body: notification(sesRecord(TEAM_ID, complaint()), TOPIC_ARN, certUrl),
            })

            expect(result).toEqual({ status: 403, message: 'Invalid SNS signature' })
            expect(mockFetch).not.toHaveBeenCalled()
            expect(writes()).toEqual({})
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
                const body = notification(sesRecord(TEAM_ID, complaint()))

                expect((await service.handle({ body })).status).toBe(status)
                expect(suppression.recordComplaints).not.toHaveBeenCalled()
                expect((await service.handle({ body })).status).toBe(200)
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
                    Timestamp: '2026-01-01T00:00:01.000Z',
                    SignatureVersion: '1',
                    Signature: '',
                    SigningCertURL: CERT_URL,
                })
            )

            const result = await service.handle({ body })

            expect(result.status).toBe(status)
            expect(mockFetch.mock.calls.filter(([url]) => url === subscribeUrl)).toHaveLength(confirmations)
        })
    })

    describe('attribution', () => {
        it('ignores feedback about mail from another sender', async () => {
            const record = sesRecord(TEAM_ID, complaint(), { source: 'someone@example.com' })

            const result = await service.handle({ body: notification(record) })

            expect(result.status).toBe(200)
            expect(writes()).toEqual({})
            expect(monitoring.queueAppMetric).not.toHaveBeenCalled()
            expect(capture).not.toHaveBeenCalled()
        })

        it.each([
            ['no tags', undefined],
            ['a missing team tag', sandboxTags(TEAM_ID, { ph_sbx_team: undefined })],
            ['a non-numeric team tag', sandboxTags(TEAM_ID, { ph_sbx_team: ['42abc'] })],
            ['two team tag values', sandboxTags(TEAM_ID, { ph_sbx_team: ['42', '43'] })],
            ['a flow tag that is not a UUID', sandboxTags(TEAM_ID, { ph_sbx_flow: ['not-a-uuid'] })],
            ['a run tag that is not a UUID', sandboxTags(TEAM_ID, { ph_sbx_run: ['run'] })],
            ['an action tag with a forbidden character', sandboxTags(TEAM_ID, { ph_sbx_action: ['action.1'] })],
            ['a non-numeric version tag', sandboxTags(TEAM_ID, { ph_sbx_version: ['v3'] })],
            ['a test tag that is not a boolean', sandboxTags(TEAM_ID, { ph_sbx_test: ['yes'] })],
            ['an empty parent run tag', sandboxTags(TEAM_ID, { ph_sbx_parent_run: [] })],
            ['a parent run tag with a forbidden character', sandboxTags(TEAM_ID, { ph_sbx_parent_run: ['run.1'] })],
        ])('acknowledges and counts a record with %s', async (_label, tags) => {
            const before = await counterValue('cdp_sandbox_email_feedback_unattributed_total', {
                event_type: 'Complaint',
            })

            const result = await service.handle({ body: notification(sesRecord(TEAM_ID, complaint(), { tags })) })

            expect(result.status).toBe(200)
            expect(writes()).toEqual({})
            expect(capture).not.toHaveBeenCalled()
            expect(
                await counterValue('cdp_sandbox_email_feedback_unattributed_total', { event_type: 'Complaint' })
            ).toBe(before + 1)
        })
    })

    describe('suppression and reporting', () => {
        const strict = { throwOnFailure: true }

        it.each([
            {
                label: 'a permanent bounce suppresses the address for the team and globally',
                event: permanentBounce(),
                writes: {
                    recordHardBounces: [[TEAM_ID, [RECIPIENT], 'smtp; 550 5.1.1 user unknown', strict]],
                    recordGlobalHardBounces: [[[RECIPIENT], '2026-01-01T00:00:02.000Z', strict]],
                },
                metric: 'email_sandbox_bounced',
                event_name: 'workflows sandbox email bounced',
                bounce_type: 'hard',
            },
            {
                label: 'a transient bounce counts toward suppression',
                event: {
                    eventType: 'Bounce',
                    bounce: {
                        bounceType: 'Transient',
                        bouncedRecipients: [{ emailAddress: RECIPIENT, diagnosticCode: 'smtp; 452 mailbox full' }],
                        timestamp: '2026-01-01T00:00:02.000Z',
                    },
                },
                writes: { recordTransientBounces: [[TEAM_ID, [RECIPIENT], 'smtp; 452 mailbox full', strict]] },
                metric: 'email_sandbox_bounced',
                event_name: 'workflows sandbox email bounced',
                bounce_type: 'soft',
            },
            {
                label: 'a complaint suppresses the address',
                event: complaint(),
                writes: { recordComplaints: [[TEAM_ID, [RECIPIENT], 'abuse', strict]] },
                metric: 'email_sandbox_complained',
                event_name: 'workflows sandbox email complained',
            },
            {
                label: 'a delivery resets the bounce counters, global list included',
                event: {
                    eventType: 'Delivery',
                    delivery: { timestamp: '2026-01-01T00:00:02.000Z', recipients: [RECIPIENT] },
                },
                writes: {
                    recordDeliveries: [
                        [TEAM_ID, [RECIPIENT], '2026-01-01T00:00:02.000Z', { clearGlobal: true, ...strict }],
                    ],
                },
                metric: 'email_sandbox_delivered',
                event_name: 'workflows sandbox email delivered',
            },
        ])('$label', async ({ event, writes: expectedWrites, metric, event_name, bounce_type }) => {
            const result = await service.handle({ body: notification(sesRecord(TEAM_ID, event)) })

            expect(result.status).toBe(200)
            expect(writes()).toEqual(expectedWrites)
            expect(monitoring.queueAppMetric.mock.calls).toEqual([
                [
                    {
                        team_id: TEAM_ID,
                        app_source_id: FLOW_ID,
                        instance_id: 'action_email_sandbox_1',
                        metric_kind: 'email',
                        metric_name: metric,
                        count: 1,
                        app_source_version: { id: FLOW_ID, version: 3 },
                    },
                    'hog_flow',
                ],
            ])
            expect(monitoring.flush).toHaveBeenCalled()
            expect(capture.mock.calls).toEqual([
                [
                    team,
                    event_name,
                    {
                        workflow_id: FLOW_ID,
                        action_id: 'action_email_sandbox_1',
                        is_test: false,
                        ...(bounce_type ? { bounce_type } : {}),
                    },
                ],
            ])
        })

        it.each([
            ['a "not-spam" complaint', complaint('not-spam')],
            ['a bounce naming an address the email was not sent to', permanentBounce('other@example.com')],
        ])('changes and reports nothing for %s', async (_label, event) => {
            const result = await service.handle({ body: notification(sesRecord(TEAM_ID, event)) })

            expect(result.status).toBe(200)
            expect(writes()).toEqual({})
            expect(monitoring.queueAppMetric).not.toHaveBeenCalled()
            expect(capture).not.toHaveBeenCalled()
        })

        it('counts feedback from a batch-triggered run under the parent run', async () => {
            const parentRunId = '0190a7f2-1c2b-7d3e-8f40-0000000000aa'
            const tags = sandboxTags(TEAM_ID, { ph_sbx_parent_run: [parentRunId] })

            await service.handle({ body: notification(sesRecord(TEAM_ID, complaint(), { tags })) })

            expect(monitoring.queueAppMetric).toHaveBeenCalledWith(
                expect.objectContaining({
                    app_source_id: parentRunId,
                    app_source_version: { id: FLOW_ID, version: 3 },
                }),
                'hog_flow'
            )
        })

        it('still suppresses after a test send, and reports it as an event only', async () => {
            const record = sesRecord(TEAM_ID, complaint(), { tags: sandboxTags(TEAM_ID, { ph_sbx_test: ['true'] }) })

            const result = await service.handle({ body: notification(record) })

            expect(result.status).toBe(200)
            expect(writes()).toEqual({ recordComplaints: [[TEAM_ID, [RECIPIENT], 'abuse', strict]] })
            expect(monitoring.queueAppMetric).not.toHaveBeenCalled()
            expect(capture).toHaveBeenCalledWith(team, 'workflows sandbox email complained', {
                workflow_id: FLOW_ID,
                action_id: 'action_email_sandbox_1',
                is_test: true,
            })
        })

        it('answers 500 without reporting when a suppression write fails, so SNS retries', async () => {
            suppression.recordComplaints.mockRejectedValue(new Error('database unavailable'))

            const result = await service.handle({ body: notification(sesRecord(TEAM_ID, complaint())) })

            expect(result.status).toBe(500)
            expect(monitoring.queueAppMetric).not.toHaveBeenCalled()
            expect(capture).not.toHaveBeenCalled()
        })

        it.each([
            [
                'fails',
                () => {
                    monitoring.flush.mockRejectedValue(new Error('kafka unavailable'))
                    capture.mockImplementation(() => {
                        throw new Error('capture failed')
                    })
                },
            ],
            ['stalls', () => monitoring.flush.mockReturnValue(new Promise(() => {}))],
        ])('answers 200 when reporting %s after the suppression write', async (_label, breakReporting) => {
            breakReporting()

            const result = await service.handle({ body: notification(sesRecord(TEAM_ID, complaint())) })

            expect(result.status).toBe(200)
            expect(suppression.recordComplaints).toHaveBeenCalled()
        })
    })
})

describe('POST /public/m/ses_sandbox_webhook', () => {
    let hub: Hub
    let team: Team
    let server: Server
    let app: express.Application

    const startApi = (): void => {
        const api = new CdpApi(hub, createCdpConsumerDeps(hub), {
            hogQueue: createMockJobQueue(),
            hogflowQueue: createMockJobQueue(),
        })
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    }

    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team
        mockFetch.mockImplementation((url) =>
            Promise.resolve({
                status: 200,
                headers: {},
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(url.endsWith('.pem') ? publicKeyPem : ''),
            } as FetchResponse)
        )
    })

    afterEach(async () => {
        server.close()
        await closeHub(hub)
    })

    it('fails closed when the topic allowlist is not configured', async () => {
        startApi()

        const res = await supertest(app)
            .post('/public/m/ses_sandbox_webhook')
            .set('Content-Type', 'text/plain')
            .send(notification(sesRecord(team.id, complaint())))

        expect(res.status).toBe(503)
    })

    it('suppresses the recipient of a signed sandbox complaint', async () => {
        hub.SES_SANDBOX_ALLOWED_SNS_TOPIC_ARNS = TOPIC_ARN
        hub.SES_SANDBOX_FROM_ADDRESS = FROM_ADDRESS
        startApi()

        const res = await supertest(app)
            .post('/public/m/ses_sandbox_webhook')
            .set('Content-Type', 'text/plain')
            .send(notification(sesRecord(team.id, complaint())))

        expect(res.status).toBe(200)
        const rows = await hub.postgres.query<{ source: string; suppressed: boolean }>(
            PostgresUse.COMMON_READ,
            `SELECT source, suppressed FROM posthog_messagesuppression WHERE team_id = $1 AND identifier = $2`,
            [team.id, RECIPIENT],
            'test-read-sandbox-suppression'
        )
        expect(rows.rows).toEqual([{ source: 'COMPLAINT', suppressed: true }])
    })
})
