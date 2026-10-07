import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFunction } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { CdpApi } from '~/cdp/cdp-api'
import { CyclotronJobInvocationHogFunction, HogFunctionType } from '~/cdp/types'
import { setupExpressApp } from '~/common/api/router'
import { defaultConfig } from '~/common/config/config'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import * as envUtils from '~/common/utils/env-utils'
import * as analytics from '~/common/utils/posthog'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { WorkflowsActivationReporter } from '../monitoring/workflows-activation-reporter'
import { WorkflowsExternalDeliveryReporter } from '../monitoring/workflows-external-delivery-reporter'
import {
    METRIC_NAME_TO_EVENT_NAME,
    PIXEL_GIF,
    addTrackingToEmail,
    decodeHtmlEntitiesInHref,
    resolveEmailEngagementDistinctId,
} from './email-tracking.service'
import { SesWebhookHandler } from './helpers/ses'
import { EmailTrackingCodeSigner, TRACKING_CODE_HEADER_NAME } from './helpers/tracking-code'

describe('EmailTrackingService', () => {
    let hub: Hub
    let team: Team

    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, defaultConfig.CDP_EMAIL_TRACKING_URL)

    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team

        mockFetch.mockClear()
        mockProducerObserver.resetKafkaProducer()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('addTrackingToEmail', () => {
        const invocation = {
            functionId: 'fn-1',
            id: 'inv-1',
            teamId: 1,
        } as any

        const extractTarget = (html: string): string => {
            const match = html.match(/href="[^"]*target=([^"&]+)/)
            if (!match) {
                throw new Error(`no tracking href in: ${html}`)
            }
            return decodeURIComponent(match[1])
        }

        it.each([
            [
                'named entity &amp;',
                '<body><a href="https://example.com/?foo=bar&amp;baz=bop">x</a></body>',
                'https://example.com/?foo=bar&baz=bop',
            ],
            [
                'decimal numeric entity &#38;',
                '<body><a href="https://example.com/?a=1&#38;b=2">x</a></body>',
                'https://example.com/?a=1&b=2',
            ],
            [
                'hex numeric entity &#x26;',
                '<body><a href="https://example.com/?a=1&#x26;b=2">x</a></body>',
                'https://example.com/?a=1&b=2',
            ],
            [
                'plain URL with no entities',
                '<body><a href="https://example.com/path">x</a></body>',
                'https://example.com/path',
            ],
        ])('decodes %s in the redirect target', (_name, html, expected) => {
            expect(extractTarget(addTrackingToEmail(html, invocation, signer))).toBe(expected)
        })

        // The pixel and redirect URLs are the only tracking carrier for a provider whose opens and
        // clicks we record ourselves, so a version missing here means those engagement metrics never
        // split by version however the send path is configured.
        it('carries the sending version into the pixel and redirect codes', () => {
            const flowInvocation = { ...invocation, hogFlow: { id: 'flow-1', version: 7 } } as any
            const html = '<body><a href="https://example.com/">x</a></body>'

            const out = addTrackingToEmail(html, flowInvocation, signer)
            const codes = [...out.matchAll(/ph_id=([A-Za-z0-9_.-]+)/g)].map((match) => match[1])

            expect(codes).toHaveLength(2) // one redirect, one pixel
            for (const code of codes) {
                expect(signer.parse(code)?.workflowVersion).toBe(7)
            }
        })

        it('mints no version for a hog function send, which has no workflow', () => {
            const out = addTrackingToEmail('<body><a href="https://example.com/">x</a></body>', invocation, signer)
            const code = out.match(/ph_id=([A-Za-z0-9_.-]+)/)![1]

            expect(signer.parse(code)?.workflowVersion).toBeUndefined()
        })

        it('skips literal javascript: hrefs', () => {
            const html = '<body><a href="javascript:alert(1)">x</a></body>'
            const out = addTrackingToEmail(html, invocation, signer)
            expect(out).toContain('href="javascript:alert(1)"')
            expect(out).not.toContain('target=')
        })

        it('skips entity-encoded javascript: hrefs after decoding', () => {
            const html = '<body><a href="java&#x73;cript:alert(1)">x</a></body>'
            const out = addTrackingToEmail(html, invocation, signer)
            expect(out).toContain('href="java&#x73;cript:alert(1)"')
            expect(out).not.toContain('target=')
        })

        it.each([
            ['clicktracking="off"', '<body><a href="https://example.com" clicktracking="off">x</a></body>'],
            ['data-ph-no-track', '<body><a href="https://example.com" data-ph-no-track>x</a></body>'],
        ])('leaves the href untouched when the anchor opts out via %s', (_name, html) => {
            const out = addTrackingToEmail(html, invocation, signer)
            expect(out).toContain('href="https://example.com"')
            expect(out).not.toContain('target=')
        })

        it('still wraps the link when the opt-out marker is on a child, not the anchor tag', () => {
            const html = '<body><a href="https://example.com"><span data-ph-no-track>x</span></a></body>'
            const out = addTrackingToEmail(html, invocation, signer)
            expect(out).toContain('target=')
        })

        describe('ses mode', () => {
            const sesTrack = (html: string): string => addTrackingToEmail(html, invocation, signer, false, 'ses')

            it('leaves hrefs pointing at the destination and tags each anchor by position', () => {
                const out = sesTrack(
                    '<body><a href="https://example.com/a">a</a><a href="https://example.com/b">b</a></body>'
                )
                // A wrapper here would bury the destination inside a per-send URL that SES then
                // reports verbatim as click.link, which is what makes per-link counts impossible.
                expect(out).not.toContain('/public/m/redirect')
                expect(out).toContain('<a href="https://example.com/a" ses:tags="phl:0">')
                expect(out).toContain('<a href="https://example.com/b" ses:tags="phl:1">')
            })

            it.each([
                ['clicktracking="off"', '<body><a href="https://example.com" clicktracking="off">x</a></body>'],
                ['data-ph-no-track', '<body><a href="https://example.com" data-ph-no-track>x</a></body>'],
            ])('translates the %s opt-out into ses:no-track', (_name, html) => {
                // SES honors only its own attribute, so without this the anchor is still rewritten
                // to awstrack.me and app deeplinks stop resolving.
                const out = sesTrack(html)
                expect(out).toContain('ses:no-track')
                expect(out).not.toContain('ses:tags')
            })

            it('merges into an author-supplied ses:tags value instead of emitting a second attribute', () => {
                const out = sesTrack('<body><a href="https://example.com" ses:tags="campaign:spring">x</a></body>')
                expect(out).toContain('ses:tags="campaign:spring;phl:0"')
            })

            it('keeps anchor positions stable when an earlier link opts out', () => {
                const out = sesTrack(
                    '<body><a href="https://example.com/a" data-ph-no-track>a</a><a href="https://example.com/b">b</a></body>'
                )
                expect(out).toContain('ses:tags="phl:1"')
            })
        })

        const invocationWithDistinctId = {
            functionId: 'fn-1',
            id: 'inv-1',
            teamId: 1,
            state: { globals: { event: { distinct_id: 'leaky-id' } } },
        } as any
        const phIdOf = (html: string): string => html.match(/ph_id=([A-Za-z0-9._-]+)/)![1]

        it('includes distinct_id in the public tracking URLs in dev/test', () => {
            const out = addTrackingToEmail(
                '<body><a href="https://example.com">x</a></body>',
                invocationWithDistinctId,
                signer
            )
            expect(signer.parse(phIdOf(out))?.distinctId).toBe('leaky-id')
        })

        it('omits distinct_id from the public tracking URLs in production (Referer-leak guard)', () => {
            const devSpy = jest.spyOn(envUtils, 'isDevEnv').mockReturnValue(false)
            const testSpy = jest.spyOn(envUtils, 'isTestEnv').mockReturnValue(false)
            try {
                const out = addTrackingToEmail(
                    '<body><a href="https://example.com">x</a></body>',
                    invocationWithDistinctId,
                    signer
                )
                expect(signer.parse(phIdOf(out))?.distinctId).toBeUndefined()
            } finally {
                devSpy.mockRestore()
                testSpy.mockRestore()
            }
        })
    })

    describe('decodeHtmlEntitiesInHref', () => {
        it.each([
            ['https://example.com/?a=1&amp;b=2', 'https://example.com/?a=1&b=2'],
            ['https://example.com/?a=1&#38;b=2', 'https://example.com/?a=1&b=2'],
            ['https://example.com/?a=1&#x26;b=2', 'https://example.com/?a=1&b=2'],
            ['https://example.com/?a=1&amp;b=2&amp;c=3', 'https://example.com/?a=1&b=2&c=3'],
            ['https://example.com/path', 'https://example.com/path'],
            // Non-entity ampersands (legacy unencoded HTML) pass through untouched.
            ['https://example.com/?a=1&b=2', 'https://example.com/?a=1&b=2'],
            // Out-of-range code points (> 0x10FFFF) must not throw RangeError;
            // the entity is left as-is.
            ['https://example.com/?x=&#x200000;', 'https://example.com/?x=&#x200000;'],
            ['https://example.com/?x=&#2097152;', 'https://example.com/?x=&#2097152;'],
        ])('decodes %s to %s', (input, expected) => {
            expect(decodeHtmlEntitiesInHref(input)).toBe(expected)
        })
    })

    describe('api', () => {
        let api: CdpApi
        let app: express.Application
        let hogFunction: HogFunctionType
        const invocationId = 'invocation-id'
        let server: Server

        beforeEach(async () => {
            api = new CdpApi(hub, createCdpConsumerDeps(hub), {
                hogQueue: createMockJobQueue(),
                hogflowQueue: createMockJobQueue(),
            })
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            hogFunction = await insertHogFunction(hub.postgres, team.id)
        })

        afterEach(() => {
            server.close()
        })

        // In production, opens/clicks come from SES webhooks. In dev/test (which jest runs as)
        // there is no SES, so the pixel/redirect handlers themselves emit the metric — these
        // tests run in test env and exercise that path.
        describe('handleEmailTrackingRedirect', () => {
            it('should redirect to the target url and record an email_link_clicked metric', async () => {
                const phId = signer.generate({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/redirect?ph_id=${phId}&target=https://example.com`)
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com')

                await waitForExpect(() => {
                    const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    expect(messages).toHaveLength(1)
                    expect(messages[0].value).toMatchObject({
                        team_id: team.id,
                        metric_name: 'email_link_clicked',
                        metric_kind: 'email',
                    })
                })
            })

            it('should return 404 if the target is not provided', async () => {
                const phId = signer.generate({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/redirect?ph_id=${phId}`)
                expect(res.status).toBe(404)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })

        describe('email tracking pixel', () => {
            it('should return a gif image and record an email_opened metric', async () => {
                const phId = signer.generate({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const res = await supertest(app).get(`/public/m/pixel?ph_id=${phId}`)
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                await waitForExpect(() => {
                    const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    expect(messages).toHaveLength(1)
                    expect(messages[0].value).toMatchObject({
                        team_id: team.id,
                        metric_name: 'email_opened',
                        metric_kind: 'email',
                    })
                })
            })

            it('should return a 200 even if the tracking code is invalid', async () => {
                const res = await supertest(app).get(`/public/m/pixel?ph_id=invalid-tracking-code`)
                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toBe('image/gif')
                expect(res.body).toEqual(PIXEL_GIF)

                const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(messages).toHaveLength(0)
            })
        })

        describe('SES webhook log entries', () => {
            // The route enforces a real SNS signature; verifying it needs AWS's private key, so we
            // stub the check and let a posted SNS envelope flow through the real handler + service.
            let verifySignatureSpy: jest.SpyInstance
            let reportSpy: jest.SpyInstance

            beforeEach(() => {
                verifySignatureSpy = jest
                    .spyOn(SesWebhookHandler.prototype as any, 'verifySnsSignature')
                    .mockResolvedValue(true)
                reportSpy = jest.spyOn(WorkflowsActivationReporter.prototype, 'report')
            })

            afterEach(() => {
                verifySignatureSpy.mockRestore()
                reportSpy.mockRestore()
            })

            const postBounce = async ({
                functionId,
                parentRunId,
                workflowVersion,
            }: {
                functionId: string
                parentRunId?: string
                workflowVersion?: number
            }): Promise<supertest.Response> => {
                // Third arg opts into the versioned payload, which `generate` won't emit by default
                // until phase two of the rollout — see EMIT_VERSIONED_PAYLOAD in tracking-code.ts.
                const trackingCode = signer.generate(
                    { functionId, id: invocationId, teamId: team.id, parentRunId, workflowVersion },
                    false,
                    workflowVersion !== undefined
                )
                const sesRecord = {
                    eventType: 'Bounce',
                    mail: {
                        timestamp: '2024-01-01T00:00:00.000Z',
                        source: 'sender@posthog.com',
                        messageId: 'ses-message-id',
                        destination: ['user@example.com'],
                        headers: [{ name: TRACKING_CODE_HEADER_NAME, value: trackingCode }],
                    },
                    bounce: {
                        bounceType: 'Permanent',
                        bouncedRecipients: [{ emailAddress: 'user@example.com' }],
                        timestamp: '2024-01-01T00:00:00.000Z',
                    },
                }
                const envelope = {
                    Type: 'Notification',
                    MessageId: 'sns-message-id',
                    TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                    Message: JSON.stringify(sesRecord),
                    Timestamp: '2024-01-01T00:00:00.000Z',
                    SignatureVersion: '1',
                    Signature: 'stubbed',
                    SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
                }
                return await supertest(app)
                    .post('/public/m/ses_webhook')
                    .set('Content-Type', 'text/plain')
                    .send(JSON.stringify(envelope))
            }

            it('writes a hog_flow log entry for a bounce that resolves to a flow', async () => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )

                const res = await postBounce({ functionId: hogFlow.id })
                expect(res.status).toBe(200)

                await waitForExpect(() => {
                    const logs = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                    expect(logs).toHaveLength(1)
                    expect(logs[0].value).toMatchObject({
                        team_id: team.id,
                        log_source: 'hog_flow',
                        log_source_id: hogFlow.id,
                        instance_id: invocationId,
                        level: 'error',
                    })
                    expect(logs[0].value.message).toContain('Permanent bounce to user@example.com')
                })

                const metrics = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                // Permanent bounces emit the rollup plus the hard-only sub-metric
                expect(metrics.map((m) => m.value.metric_name)).toEqual(['email_bounced', 'email_bounced_hard'])
                expect(metrics[0].value).toMatchObject({
                    team_id: team.id,
                    metric_name: 'email_bounced',
                    metric_kind: 'email',
                })
            })

            it('records the metric but writes no log entry when the bounce resolves to a hog_function', async () => {
                const res = await postBounce({ functionId: hogFunction.id })
                expect(res.status).toBe(200)

                await waitForExpect(() => {
                    const metrics = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    // Permanent bounces emit the rollup plus the hard-only sub-metric
                    expect(metrics.map((m) => m.value.metric_name)).toEqual(['email_bounced', 'email_bounced_hard'])
                    expect(metrics[0].value).toMatchObject({
                        team_id: team.id,
                        metric_name: 'email_bounced',
                    })
                })

                const logs = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                expect(logs).toHaveLength(0)
            })

            it('attributes the bounce to the version that sent it, not the version live when it lands', async () => {
                // The workflow has been republished since the send. Reading the version off the flow
                // manager here would blame v5 for v2's bounce — which is precisely the comparison
                // ("did the new version bounce more?") the versioned series exists to answer.
                const hogFlow = await insertHogFlow(hub.postgres, {
                    ...new FixtureHogFlowBuilder().withTeamId(team.id).build(),
                    version: 5,
                })

                const res = await postBounce({ functionId: hogFlow.id, workflowVersion: 2 })
                expect(res.status).toBe(200)

                await waitForExpect(() => {
                    const metrics = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    const versioned = metrics.filter((m) => m.value.app_source === 'hog_flow_version')
                    // Permanent bounces emit the rollup plus the hard-only sub-metric, so both mirror.
                    expect(versioned.map((m) => m.value.app_source_id)).toEqual([`${hogFlow.id}/2`, `${hogFlow.id}/2`])
                    // Mirrored, not moved — the version-agnostic series every existing reader uses
                    // still carries the same two rows.
                    expect(
                        metrics.filter((m) => m.value.app_source === 'hog_flow').map((m) => m.value.metric_name)
                    ).toEqual(['email_bounced', 'email_bounced_hard'])
                })
            })

            const senderFunctionId = async (
                sender: 'workflow' | 'deleted workflow' | 'hog function'
            ): Promise<string> => {
                if (sender === 'workflow') {
                    return (await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build()))
                        .id
                }
                return sender === 'deleted workflow' ? '0190f0c4-0000-7000-8000-000000000220' : hogFunction.id
            }

            it.each([
                ['reports a delivered workflow message', 'workflow', 1, true],
                ['reports a message delivered after its workflow was deleted', 'deleted workflow', 1, true],
                ['does not report a delivered hog function message', 'hog function', undefined, false],
            ] as const)('%s as a workflows activation step', async (_name, sender, workflowVersion, reported) => {
                const functionId = await senderFunctionId(sender)
                const trackingCode = signer.generate({ functionId, id: invocationId, teamId: team.id, workflowVersion })
                const sesRecord = {
                    eventType: 'Delivery',
                    mail: {
                        timestamp: '2024-01-01T00:00:00.000Z',
                        source: 'sender@posthog.com',
                        messageId: 'ses-message-id',
                        destination: ['user@example.com'],
                        headers: [{ name: TRACKING_CODE_HEADER_NAME, value: trackingCode }],
                    },
                    delivery: { timestamp: '2024-01-01T00:00:01.000Z', recipients: ['user@example.com'] },
                }

                const res = await supertest(app)
                    .post('/public/m/ses_webhook')
                    .set('Content-Type', 'text/plain')
                    .send(
                        JSON.stringify({
                            Type: 'Notification',
                            MessageId: 'sns-message-id',
                            TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                            Message: JSON.stringify(sesRecord),
                            Timestamp: '2024-01-01T00:00:01.000Z',
                            SignatureVersion: '1',
                            Signature: 'stubbed',
                            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
                        })
                    )

                expect(res.status).toBe(200)
                expect(reportSpy.mock.calls).toEqual(
                    reported
                        ? [[team.id, 'workflows message delivered', { channel: 'email', workflow_id: functionId }]]
                        : []
                )
            })

            it('keys the log entry under parentRunId for batch-triggered runs', async () => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                const parentRunId = 'batch-run-id'

                const res = await postBounce({ functionId: hogFlow.id, parentRunId })
                expect(res.status).toBe(200)

                await waitForExpect(() => {
                    const logs = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                    expect(logs).toHaveLength(1)
                    expect(logs[0].value).toMatchObject({
                        log_source: 'hog_flow',
                        log_source_id: parentRunId,
                        instance_id: invocationId,
                    })
                })
            })
        })
    })

    describe('SES webhook writes to the suppression list', () => {
        // EmailSuppressionService reads its threshold from `hub.EMAIL_SUPPRESSION_*` (via CdpConfig),
        // not directly from process.env. The outer beforeEach recreates `hub` per test, so overriding
        // here doesn't leak across tests — no restore in afterEach needed. Threshold=1 keeps the test
        // to a single POST — the counter arithmetic is not what this test is guarding, the write-path
        // wiring is.
        let api: CdpApi
        let app: express.Application
        let server: Server
        let verifySignatureSpy: jest.SpyInstance

        beforeEach(() => {
            hub.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = 1

            api = new CdpApi(hub, createCdpConsumerDeps(hub), {
                hogQueue: createMockJobQueue(),
                hogflowQueue: createMockJobQueue(),
            })
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})

            verifySignatureSpy = jest
                .spyOn(SesWebhookHandler.prototype as any, 'verifySnsSignature')
                .mockResolvedValue(true)
        })

        afterEach(() => {
            server.close()
            verifySignatureSpy.mockRestore()
        })

        describe('external delivery activation', () => {
            let capture: jest.SpyInstance

            beforeEach(() => {
                capture = jest.spyOn(analytics, 'captureTeamEvent').mockImplementation(() => {})
            })

            afterEach(() => capture.mockRestore())

            const postDelivery = async (
                functionId: string,
                recipients: string[],
                options: {
                    isTest?: boolean
                    shortCode?: boolean
                    workflowVersion?: number
                    omitRecipients?: boolean
                } = {},
                targetApp: express.Application = app
            ): Promise<supertest.Response> => {
                const invocation = {
                    functionId,
                    id: 'invocation-id',
                    teamId: team.id,
                    workflowVersion: options.workflowVersion,
                }
                const trackingCode = options.shortCode
                    ? signer.generateShort(invocation)
                    : signer.generate(invocation, options.isTest)
                const timestamp = new Date().toISOString()
                const record = {
                    eventType: 'Delivery',
                    mail: {
                        timestamp,
                        source: 'sender@example.com',
                        messageId: 'ses-message-id',
                        destination: recipients,
                        ...(options.shortCode
                            ? { tags: { ph_id: [trackingCode] } }
                            : { headers: [{ name: TRACKING_CODE_HEADER_NAME, value: trackingCode }] }),
                    },
                    delivery: { timestamp, ...(options.omitRecipients ? {} : { recipients }) },
                }
                return await supertest(targetApp)
                    .post('/public/m/ses_webhook')
                    .set('Content-Type', 'text/plain')
                    .send(
                        JSON.stringify({
                            Type: 'Notification',
                            MessageId: 'sns-message-id',
                            TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                            Message: JSON.stringify(record),
                            Timestamp: timestamp,
                            SignatureVersion: '1',
                            Signature: 'stubbed',
                            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
                        })
                    )
            }

            it('reports a confirmed workflow delivery to an external recipient', async () => {
                const flow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
                const response = await postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 })
                expect(response.status).toBe(200)
                expect(capture).toHaveBeenCalledWith(
                    expect.objectContaining({ id: team.id }),
                    'workflows message delivered to external recipient',
                    { workflow_id: flow.id, channel: 'email' }
                )
            })

            it('acknowledges delivery when activation reporting stalls', async () => {
                const flow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
                expect((await postTransientBounce(flow.id, 'reader@example.com')).status).toBe(200)
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_messagesuppression SET suppressed = false WHERE team_id = $1 AND identifier = $2',
                    [team.id, 'reader@example.com'],
                    'setUnsuppressedBounceFixture'
                )
                const reporting = jest
                    .spyOn(WorkflowsExternalDeliveryReporter.prototype, 'report')
                    .mockImplementationOnce(() => new Promise(() => {}))
                try {
                    expect((await postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 })).status).toBe(
                        200
                    )
                    const result = await hub.postgres.query<{ transient_bounce_count: number }>(
                        PostgresUse.COMMON_WRITE,
                        'SELECT transient_bounce_count FROM posthog_messagesuppression WHERE team_id = $1 AND identifier = $2',
                        [team.id, 'reader@example.com'],
                        'testDeliveryResetAfterReportingStall'
                    )
                    expect(result.rows).toEqual([{ transient_bounce_count: 0 }])
                } finally {
                    reporting.mockRestore()
                }
            }, 3000)

            it.each([false, true])(
                'does not activate on delivery to an organization member with uppercase %s',
                async (uppercase) => {
                    const address = `member-${team.id}@example.com`
                    const recipient = uppercase ? address.toUpperCase() : address
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        'UPDATE posthog_user SET email = $1 WHERE id IN (SELECT user_id FROM posthog_organizationmembership WHERE organization_id = $2)',
                        [`Member-${team.id}@example.com`, team.organization_id],
                        'setActivationMemberEmail'
                    )
                    const flow = await insertHogFlow(
                        hub.postgres,
                        new FixtureHogFlowBuilder().withTeamId(team.id).build()
                    )
                    expect((await postDelivery(flow.id, [recipient], { workflowVersion: 1 })).status).toBe(200)
                    expect(capture).not.toHaveBeenCalled()
                    expect((await postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 })).status).toBe(
                        200
                    )
                    expect(capture).toHaveBeenCalledTimes(1)
                }
            )

            it('reports once across concurrent webhook workers', async () => {
                const flow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
                const otherApi = new CdpApi(hub, createCdpConsumerDeps(hub), {
                    hogQueue: createMockJobQueue(),
                    hogflowQueue: createMockJobQueue(),
                })
                const otherApp = setupExpressApp()
                otherApp.use('/', otherApi.router())
                const otherServer = otherApp.listen(0, () => {})
                try {
                    const responses = await Promise.all([
                        postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 }),
                        postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 }, otherApp),
                    ])
                    expect(responses.map(({ status }) => status)).toEqual([200, 200])
                    expect(
                        capture.mock.calls.filter(
                            ([, event]) => event === 'workflows message delivered to external recipient'
                        )
                    ).toHaveLength(1)
                    expect((await postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 })).status).toBe(
                        200
                    )
                    expect(
                        capture.mock.calls.filter(
                            ([, event]) => event === 'workflows message delivered to external recipient'
                        )
                    ).toHaveLength(1)
                } finally {
                    otherServer.close()
                }
            })

            it.each([
                ['an editor test', { isTest: true, workflowVersion: 1 }],
                ['a short tracking tag without its signed header', { shortCode: true, workflowVersion: 1 }],
                ['a delivery without confirmed recipients', { omitRecipients: true, workflowVersion: 1 }],
            ])('does not activate on %s', async (_name, options) => {
                const flow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
                expect((await postDelivery(flow.id, ['reader@example.com'], options)).status).toBe(200)
                expect(capture).not.toHaveBeenCalled()
            })

            it('does not activate on a hog function delivery', async () => {
                const fn = await insertHogFunction(hub.postgres, team.id)
                expect((await postDelivery(fn.id, ['reader@example.com'])).status).toBe(200)
                expect(capture).not.toHaveBeenCalled()
            })

            it('reports a signed workflow delivery after the workflow is deleted', async () => {
                const flow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'DELETE FROM posthog_hogflow WHERE id = $1',
                    [flow.id],
                    'deleteActivationFlow'
                )
                expect((await postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 })).status).toBe(200)
                expect(capture).toHaveBeenCalledTimes(1)
            })

            it.each(['membership lookup', 'analytics capture'])(
                'does not consume the reporting hour when %s fails',
                async (failure) => {
                    const flow = await insertHogFlow(
                        hub.postgres,
                        new FixtureHogFlowBuilder().withTeamId(team.id).build()
                    )
                    const originalQuery = hub.postgres.query.bind(hub.postgres)
                    const query = jest.spyOn(hub.postgres, 'query').mockImplementation(async (...args) => {
                        if (failure === 'membership lookup' && args[3] === 'workflowActivationMembers') {
                            throw new Error('Membership lookup unavailable')
                        }
                        return await originalQuery(...args)
                    })
                    if (failure === 'analytics capture') {
                        capture.mockImplementationOnce(() => {
                            throw new Error('Analytics unavailable')
                        })
                    }
                    try {
                        expect(
                            (await postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 })).status
                        ).toBe(200)
                    } finally {
                        query.mockRestore()
                    }
                    expect((await postDelivery(flow.id, ['reader@example.com'], { workflowVersion: 1 })).status).toBe(
                        200
                    )
                    expect(capture).toHaveBeenCalledTimes(failure === 'analytics capture' ? 2 : 1)
                }
            )
        })

        const postTransientBounce = async (functionId: string, emailAddress: string): Promise<supertest.Response> => {
            const trackingCode = signer.generate({ functionId, id: 'invocation-id', teamId: team.id })
            const sesRecord = {
                eventType: 'Bounce',
                mail: {
                    timestamp: '2024-01-01T00:00:00.000Z',
                    source: 'sender@posthog.com',
                    messageId: 'ses-message-id',
                    destination: [emailAddress],
                    headers: [{ name: TRACKING_CODE_HEADER_NAME, value: trackingCode }],
                },
                bounce: {
                    bounceType: 'Transient',
                    bouncedRecipients: [
                        { emailAddress, diagnosticCode: 'smtp; 421 4.2.1 mailbox temporarily unavailable' },
                    ],
                    timestamp: '2024-01-01T00:00:00.000Z',
                },
            }
            const envelope = {
                Type: 'Notification',
                MessageId: 'sns-message-id',
                TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                Message: JSON.stringify(sesRecord),
                Timestamp: '2024-01-01T00:00:00.000Z',
                SignatureVersion: '1',
                Signature: 'stubbed',
                SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
            }
            return await supertest(app)
                .post('/public/m/ses_webhook')
                .set('Content-Type', 'text/plain')
                .send(JSON.stringify(envelope))
        }

        const postPermanentBounce = async (functionId: string, emailAddress: string): Promise<supertest.Response> => {
            const trackingCode = signer.generate({ functionId, id: 'invocation-id', teamId: team.id })
            const sesRecord = {
                eventType: 'Bounce',
                mail: {
                    timestamp: '2024-01-01T00:00:00.000Z',
                    source: 'sender@posthog.com',
                    messageId: 'ses-message-id',
                    destination: [emailAddress],
                    headers: [{ name: TRACKING_CODE_HEADER_NAME, value: trackingCode }],
                },
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [{ emailAddress, diagnosticCode: 'smtp; 550 5.1.1 user unknown' }],
                    timestamp: '2024-01-01T00:00:00.000Z',
                },
            }
            const envelope = {
                Type: 'Notification',
                MessageId: 'sns-message-id',
                TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                Message: JSON.stringify(sesRecord),
                Timestamp: '2024-01-01T00:00:00.000Z',
                SignatureVersion: '1',
                Signature: 'stubbed',
                SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
            }
            return await supertest(app)
                .post('/public/m/ses_webhook')
                .set('Content-Type', 'text/plain')
                .send(JSON.stringify(envelope))
        }

        const postComplaint = async (functionId: string, emailAddress: string): Promise<supertest.Response> => {
            const trackingCode = signer.generate({ functionId, id: 'invocation-id', teamId: team.id })
            const sesRecord = {
                eventType: 'Complaint',
                mail: {
                    timestamp: '2024-01-01T00:00:00.000Z',
                    source: 'sender@posthog.com',
                    messageId: 'ses-message-id',
                    destination: [emailAddress],
                    headers: [{ name: TRACKING_CODE_HEADER_NAME, value: trackingCode }],
                },
                complaint: {
                    complainedRecipients: [{ emailAddress }],
                    complaintFeedbackType: 'abuse',
                    timestamp: '2024-01-01T00:00:00.000Z',
                },
            }
            const envelope = {
                Type: 'Notification',
                MessageId: 'sns-message-id',
                TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                Message: JSON.stringify(sesRecord),
                Timestamp: '2024-01-01T00:00:00.000Z',
                SignatureVersion: '1',
                Signature: 'stubbed',
                SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
            }
            return await supertest(app)
                .post('/public/m/ses_webhook')
                .set('Content-Type', 'text/plain')
                .send(JSON.stringify(envelope))
        }

        it('inserts a suppression row and marks it suppressed after a Transient bounce webhook', async () => {
            const hogFlow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
            const email = 'transient-bouncer@example.com'

            const res = await postTransientBounce(hogFlow.id, email)
            expect(res.status).toBe(200)

            // handleSesWebhook awaits the suppression write inline, so the row is present
            // as soon as the 200 returns — no waitForExpect needed.
            const result = await hub.postgres.query<{
                identifier: string
                source: string
                suppressed: boolean
                transient_bounce_count: number
                deleted: boolean
            }>(
                PostgresUse.COMMON_READ,
                `SELECT identifier, source, suppressed, transient_bounce_count, deleted
                 FROM posthog_messagesuppression
                 WHERE team_id = $1 AND identifier = $2`,
                [team.id, email],
                'test-read-suppression'
            )
            expect(result.rows).toEqual([
                {
                    identifier: email,
                    source: 'BOUNCE',
                    suppressed: true,
                    transient_bounce_count: 1,
                    deleted: false,
                },
            ])
        })

        it('inserts a suppressed row for a Permanent bounce webhook', async () => {
            const hogFlow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
            const email = 'hard-bouncer@example.com'

            const res = await postPermanentBounce(hogFlow.id, email)
            expect(res.status).toBe(200)

            const result = await hub.postgres.query<{
                identifier: string
                source: string
                suppressed: boolean
                transient_bounce_count: number
                last_bounce_diagnostic: string | null
                deleted: boolean
            }>(
                PostgresUse.COMMON_READ,
                `SELECT identifier, source, suppressed, transient_bounce_count, last_bounce_diagnostic, deleted
                 FROM posthog_messagesuppression
                 WHERE team_id = $1 AND identifier = $2`,
                [team.id, email],
                'test-read-hard-bounce-suppression'
            )
            expect(result.rows).toEqual([
                {
                    identifier: email,
                    source: 'BOUNCE',
                    suppressed: true,
                    transient_bounce_count: 0,
                    last_bounce_diagnostic: 'smtp; 550 5.1.1 user unknown',
                    deleted: false,
                },
            ])
        })

        it('inserts a suppressed row for a Complaint webhook', async () => {
            const hogFlow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
            const email = 'complainer@example.com'

            const res = await postComplaint(hogFlow.id, email)
            expect(res.status).toBe(200)

            const result = await hub.postgres.query<{
                identifier: string
                source: string
                suppressed: boolean
                transient_bounce_count: number
                deleted: boolean
            }>(
                PostgresUse.COMMON_READ,
                `SELECT identifier, source, suppressed, transient_bounce_count, deleted
                 FROM posthog_messagesuppression
                 WHERE team_id = $1 AND identifier = $2`,
                [team.id, email],
                'test-read-complaint-suppression'
            )
            expect(result.rows).toEqual([
                {
                    identifier: email,
                    source: 'COMPLAINT',
                    suppressed: true,
                    transient_bounce_count: 0,
                    deleted: false,
                },
            ])
        })
    })

    describe('resolveEmailEngagementDistinctId', () => {
        const buildInvocation = (
            globals: Partial<NonNullable<CyclotronJobInvocationHogFunction['state']['globals']>>
        ): CyclotronJobInvocationHogFunction =>
            ({
                state: { globals: globals as any },
            }) as CyclotronJobInvocationHogFunction

        it.each([
            {
                name: 'uses event.distinct_id (native for event-triggered; backfilled by the worker for batch)',
                globals: { event: { distinct_id: 'user-from-event' } },
                expected: 'user-from-event',
            },
            {
                // Empty event.distinct_id means no distinct_id resolved upstream; we must NOT derive
                // one from globals.person — person.id is the uuid (phantom person) and person.distinct_id
                // is the same source already folded into event.distinct_id.
                name: 'ignores globals.person and returns undefined when event.distinct_id is empty',
                globals: { event: { distinct_id: '' }, person: { id: 'person-uuid', distinct_id: 'person-distinct' } },
                expected: undefined,
            },
            {
                name: 'returns undefined when there is no event',
                globals: {},
                expected: undefined,
            },
        ])('$name', ({ globals, expected }) => {
            expect(resolveEmailEngagementDistinctId(buildInvocation(globals as any))).toBe(expected)
        })
    })

    describe('METRIC_NAME_TO_EVENT_NAME allowlist', () => {
        it('maps every email metric we want to surface and excludes internal ones', () => {
            // Adding entries here changes the set of events customers can build insights on top of —
            // treat as a public-API change. Removing entries leaves customers with broken insights.
            expect(METRIC_NAME_TO_EVENT_NAME).toEqual({
                email_sent: '$workflows_email_sent',
                email_failed: '$workflows_email_failed',
                email_delivered: '$workflows_email_delivered',
                email_opened: '$workflows_email_opened',
                email_link_clicked: '$workflows_email_link_clicked',
                email_bounced: '$workflows_email_bounced',
                email_blocked: '$workflows_email_blocked',
            })
        })
    })
})
