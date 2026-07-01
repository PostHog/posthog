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
import * as envUtils from '~/common/utils/env-utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
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
        await resetTestDatabase()
        hub = await createHub({})
        team = await getFirstTeam(hub.postgres)

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

            beforeEach(() => {
                verifySignatureSpy = jest
                    .spyOn(SesWebhookHandler.prototype as any, 'verifySnsSignature')
                    .mockResolvedValue(true)
            })

            afterEach(() => {
                verifySignatureSpy.mockRestore()
            })

            const postBounce = async ({
                functionId,
                parentRunId,
            }: {
                functionId: string
                parentRunId?: string
            }): Promise<supertest.Response> => {
                const trackingCode = signer.generate({
                    functionId,
                    id: invocationId,
                    teamId: team.id,
                    parentRunId,
                })
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
                expect(metrics).toHaveLength(1)
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
                    expect(metrics).toHaveLength(1)
                    expect(metrics[0].value).toMatchObject({
                        team_id: team.id,
                        metric_name: 'email_bounced',
                    })
                })

                const logs = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                expect(logs).toHaveLength(0)
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
