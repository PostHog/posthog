import '~/tests/helpers/mocks/consumer.mock'
import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch, mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { Server } from 'http'
import { Message } from 'node-rdkafka'
import { register } from 'prom-client'
import supertest from 'supertest'
import express from 'ultimate-express'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import {
    createExampleInvocation,
    createKafkaMessage,
    insertHogFunction,
    insertIntegration,
} from '~/cdp/_tests/fixtures'
import { hideHogFlowsFromReplica, insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { CdpApi } from '~/cdp/cdp-api'
import { CdpSesWebhooksConsumer } from '~/cdp/consumers/cdp-ses-webhooks.consumer'
import { CyclotronJobInvocationHogFunction, HogFunctionType } from '~/cdp/types'
import { setupExpressApp } from '~/common/api/router'
import { defaultConfig } from '~/common/config/config'
import {
    KAFKA_APP_METRICS_2,
    KAFKA_CDP_SES_WEBHOOKS,
    KAFKA_EMAIL_STATUS,
    KAFKA_LOG_ENTRIES,
} from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import * as envUtils from '~/common/utils/env-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { TRANSACTIONAL_EMAIL_EVENT } from '../hogflows/hogflow-sensitivity'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EmailSuppressionService } from './email-suppression.service'
import {
    METRIC_NAME_TO_EVENT_NAME,
    PIXEL_GIF,
    UNSIGNED_REDIRECT_SUNSET,
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

    const queuedSesNotifications = (): Message[] =>
        mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_CDP_SES_WEBHOOKS)
            .map(({ key, value }) => createKafkaMessage(value, { key: key ?? undefined }))

    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team

        mockFetch.mockClear()
        mockInternalFetch.mockClear()
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
            state: {},
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
                'uppercase named entity &AMP;',
                '<body><a href="https://example.com/?a=1&AMP;b=2">x</a></body>',
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
            const flowInvocation = { ...invocation, state: { ...invocation.state, renderedWorkflowVersion: 7 } }
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

        it.each([
            ['written out', 'javascript:alert(1)'],
            ['entity-encoded', 'java&#x73;cript:alert(1)'],
            ['split by a tab reference', 'java&#X09;script:alert(1)'],
            ['split by a newline reference', 'jav&#10;ascript:alert(1)'],
            ['split by a raw carriage return', 'java\rscript:alert(1)'],
            ['led by a control character', '&#x01;javascript:alert(1)'],
        ])('skips a javascript: href that is %s', (_, href) => {
            const out = addTrackingToEmail(`<body><a href="${href}">x</a></body>`, invocation, signer)
            expect(out).toContain(`href="${href}"`)
            expect(out).not.toContain('target=')
        })

        const sensitiveInvocation = { ...invocation, hogFunction: { metadata: { sensitive: true } } }

        it.each([
            ['clicktracking="off"', '<body><a href="https://example.com" clicktracking="off">x</a></body>', invocation],
            ['data-ph-no-track', '<body><a href="https://example.com" data-ph-no-track>x</a></body>', invocation],
            ['a sensitive template', '<body><a href="https://example.com">x</a></body>', sensitiveInvocation],
        ])('leaves the href untouched when the anchor opts out via %s', (_name, html, inv) => {
            const out = addTrackingToEmail(html, inv, signer)
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
                [
                    'a single-quoted href',
                    `<a href='https://example.com/a'>a</a>`,
                    `<a href='https://example.com/a' ses:tags="phl:0">a</a>`,
                ],
                [
                    'an unquoted href',
                    '<a href=https://example.com/a>a</a>',
                    '<a href=https://example.com/a ses:tags="phl:0">a</a>',
                ],
                [
                    'spaces around the equals sign',
                    '<a href = "https://example.com/a">a</a>',
                    '<a href = "https://example.com/a" ses:tags="phl:0">a</a>',
                ],
                [
                    'an uppercase tag',
                    '<A HREF="https://example.com/a">a</A>',
                    '<A HREF="https://example.com/a" ses:tags="phl:0">a</A>',
                ],
                [
                    'a self-closing opening tag',
                    '<a href="https://example.com/a" />a</a>',
                    '<a href="https://example.com/a" ses:tags="phl:0">a</a>',
                ],
                [
                    'a stray opener inside the tag',
                    '<a <a href="https://example.com/a">a</a>',
                    '<a <a href="https://example.com/a" ses:tags="phl:0">a</a>',
                ],
                [
                    'an unclosed anchor before a closed one',
                    '<a href="https://example.com/a">a<a href="https://example.com/b">b</a>',
                    '<a href="https://example.com/a" ses:tags="phl:0">a<a href="https://example.com/b">b</a>',
                ],
                [
                    'a named anchor after a link',
                    '<a href="https://example.com/a">a</a><a name="top">b</a>',
                    '<a href="https://example.com/a" ses:tags="phl:0">a</a><a name="top">b</a>',
                ],
                [
                    'a named anchor before a link',
                    '<a name="top">a<a href="https://example.com/b">b</a>',
                    '<a name="top">a<a href="https://example.com/b" ses:tags="phl:0">b</a>',
                ],
                [
                    'an anchor that never closes',
                    '<a href="https://example.com/a">a',
                    '<a href="https://example.com/a">a',
                ],
                [
                    'a tag that only starts with a',
                    '<abbr href="https://example.com/a">a</abbr><a href="https://example.com/b">b</a>',
                    '<abbr href="https://example.com/a">a</abbr><a href="https://example.com/b" ses:tags="phl:0">b</a>',
                ],
            ])('tags the anchors in %s', (_name, body, tagged) => {
                const out = sesTrack(`<body>${body}</body>`)
                expect(out.slice(0, out.indexOf('<img src="'))).toBe(`<body>${tagged}`)
            })

            it.each([
                [
                    'clicktracking="off"',
                    '<body><a href="https://example.com" clicktracking="off">x</a></body>',
                    invocation,
                ],
                ['data-ph-no-track', '<body><a href="https://example.com" data-ph-no-track>x</a></body>', invocation],
                ['a sensitive template', '<body><a href="https://example.com">x</a></body>', sensitiveInvocation],
            ])('translates the %s opt-out into ses:no-track', (_name, html, inv) => {
                // SES honors only its own attribute, so without this the anchor is still rewritten
                // to awstrack.me and app deeplinks stop resolving.
                const out = addTrackingToEmail(html, inv, signer, false, 'ses')
                expect(out).toContain('ses:no-track')
                expect(out).not.toContain('ses:tags')
                // Opting links out of click tracking keeps the open pixel.
                expect(out).toContain('ph_id=')
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

        it.each([
            { captureEngagement: undefined, distinctId: 'leaky-id' },
            { captureEngagement: true, distinctId: 'leaky-id' },
            { captureEngagement: false, distinctId: undefined },
        ])(
            'mints the pixel and redirect codes in dev/test with the distinct_id the send choice $captureEngagement allows',
            ({ captureEngagement, distinctId }) => {
                const out = addTrackingToEmail(
                    '<body><a href="https://example.com">x</a></body>',
                    {
                        ...invocationWithDistinctId,
                        state: {
                            ...invocationWithDistinctId.state,
                            send: captureEngagement === undefined ? undefined : { tracking: { captureEngagement } },
                        },
                    },
                    signer
                )
                const codes = [...out.matchAll(/ph_id=([A-Za-z0-9_.-]+)/g)].map((match) => signer.parse(match[1]))
                expect(codes).toHaveLength(2)
                for (const code of codes) {
                    expect(code).toMatchObject({ functionId: 'fn-1', invocationId: 'inv-1', distinctId })
                }
            }
        )

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
            ['https://example.com/?a=1&AMP;b=2&#X26;c=3', 'https://example.com/?a=1&b=2&c=3'],
            ['https://example.com/?a=1&Amp;b=2&APOS;c=3', 'https://example.com/?a=1&Amp;b=2&APOS;c=3'],
            [
                'https://example.com/?q=&#xD800;&#XDFFF;&#55296;&#x1F600;',
                'https://example.com/?q=\uFFFD\uFFFD\uFFFD\u{1F600}',
            ],
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
            const trackingCode = (): string =>
                signer.generate({ functionId: hogFunction.id, id: invocationId, teamId: team.id })

            const mintedLinkPath = (target: string): string => {
                const link = new URL(
                    signer.redirectUrl({ functionId: hogFunction.id, id: invocationId, teamId: team.id }, target)
                )
                return `${link.pathname}${link.search}`
            }

            const realNow = Date.now
            let clock: jest.SpyInstance
            // Shifts the clock instead of freezing it, because waitForExpect reads Date.now for its timeout.
            const setClock = (at: number): void => {
                const offset = at - realNow()
                clock.mockImplementation(() => realNow() + offset)
            }

            beforeEach(() => {
                clock = jest.spyOn(Date, 'now')
                setClock(UNSIGNED_REDIRECT_SUNSET - 60_000)
            })

            afterEach(() => {
                clock.mockRestore()
            })

            const expectLinkClickedMetrics = async (count: number): Promise<void> => {
                await waitForExpect(() => {
                    const messages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    expect(messages).toHaveLength(count)
                    for (const message of messages) {
                        expect(message.value).toMatchObject({
                            team_id: team.id,
                            metric_name: 'email_link_clicked',
                            metric_kind: 'email',
                        })
                    }
                })
            }

            it('should redirect a signed link after the unsigned link sunset and record an email_link_clicked metric', async () => {
                setClock(UNSIGNED_REDIRECT_SUNSET)
                const res = await supertest(app).get(mintedLinkPath('https://example.com/?a=1&b=2'))
                expect(res.status).toBe(302)
                expect(res.headers.location).toBe('https://example.com/?a=1&b=2')

                await expectLinkClickedMetrics(1)
            })

            it.each([
                [
                    'two valid hrefs',
                    `<a href="https://example.com/a" href='https://example.com/b'>x</a>`,
                    'https://example.com/b',
                ],
                [
                    'a javascript: href after a valid one',
                    '<a href="https://example.com/a" href="javascript:x">x</a>',
                    'https://example.com/a',
                ],
                ['a quoted href holding a >', '<a href="https://example.com/?a>b">x</a>', 'https://example.com/?a%3Eb'],
            ])('should redirect a tracked link in %s to its last trackable href', async (_name, anchor, expected) => {
                const html = addTrackingToEmail(
                    `<body>${anchor}</body>`,
                    { functionId: hogFunction.id, id: invocationId, teamId: team.id, state: {} } as any,
                    signer
                )
                const link = new URL(html.match(/href="([^"]+\/public\/m\/redirect[^"]+)"/)![1])

                const res = await supertest(app).get(`${link.pathname}${link.search}`)

                expect(res.status).toBe(302)
                expect(res.headers.location).toBe(expected)
            })

            it.each([
                [
                    'has no tracking code',
                    () => '/public/m/redirect?target=https://other.example/',
                    'https://other.example/',
                    0,
                ],
                [
                    'has no target signature',
                    () => `/public/m/redirect?ph_id=${trackingCode()}&target=https://other.example/`,
                    'https://other.example/',
                    1,
                ],
                [
                    'has its target swapped after signing',
                    () =>
                        mintedLinkPath('https://example.com/').replace(/target=[^&]+/, 'target=https://other.example/'),
                    'https://other.example/',
                    1,
                ],
                [
                    'carries markup in its target',
                    // The URL parser percent-encodes markup in a query or a hierarchical path, but keeps it raw in
                    // the opaque path of a mailto: URL, so only this target depends on the page escaping it.
                    () =>
                        `/public/m/redirect?target=${encodeURIComponent('mailto:"><script>alert(1)</script>@example.com')}`,
                    'mailto:&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;@example.com',
                    0,
                ],
                [
                    'points at an email address',
                    () => '/public/m/redirect?target=mailto:someone@example.com',
                    'mailto:someone@example.com',
                    0,
                ],
            ])(
                'should show a confirmation page instead of redirecting when the link %s',
                async (_name, path, expectedHref, expectedMetrics) => {
                    const res = await supertest(app).get(path())
                    expect(res.status).toBe(200)
                    expect(res.headers.location).toBeUndefined()
                    expect(res.headers).toMatchObject({
                        'content-type': 'text/html; charset=utf-8',
                        'x-content-type-options': 'nosniff',
                        'cache-control': 'no-store',
                    })
                    expect(res.headers['content-security-policy']).toContain("default-src 'none'")
                    expect(res.text).toContain(`href="${expectedHref}"`)
                    expect(res.text).not.toContain('<script')

                    await expectLinkClickedMetrics(expectedMetrics)
                }
            )

            it('should return 404 for an unsigned link after the unsigned link sunset', async () => {
                setClock(UNSIGNED_REDIRECT_SUNSET)
                const res = await supertest(app).get('/public/m/redirect?target=https://other.example/')
                expect(res.status).toBe(404)
            })

            it.each([
                ['the target is not provided', () => `/public/m/redirect?ph_id=${trackingCode()}`],
                ['an unsigned target has a script scheme', () => '/public/m/redirect?target=javascript:alert(1)'],
                ['an unsigned target opens an app', () => '/public/m/redirect?target=sms:5555550100'],
                [
                    'an unsigned target puts a username before its host',
                    () => '/public/m/redirect?target=https://posthog.com@evil.example/',
                ],
                [
                    'the target is repeated',
                    () => '/public/m/redirect?target=https://a.example/&target=https://b.example/',
                ],
            ])('should return 404 if %s', async (_name, path) => {
                const res = await supertest(app).get(path())
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

            it('counts a large audience, where most new people do not change the HyperLogLog', async () => {
                const parentRunId = new UUIDT().toString()
                const service = api['emailTrackingService'] as any
                let opened = 0
                for (let index = 0; index < 5000; index++) {
                    const added = await service.newEngagedPeople(parentRunId, `person-${index}`, 'email_opened', 'ses')
                    opened += added[0]?.count ?? 0
                }
                expect(opened).toBeGreaterThan(4900)
                expect(opened).toBeLessThan(5100)
            })

            it.each<[string, (service: any) => void]>([
                [
                    'Redis stalls',
                    (service) =>
                        jest.spyOn(service.engagementRedis, 'useClient').mockReturnValue(new Promise(() => {})),
                ],
                [
                    'Redis rejects',
                    (service) =>
                        jest
                            .spyOn(service.engagementRedis, 'useClient')
                            .mockRejectedValueOnce(new Error('pool exhausted')),
                ],
                [
                    'the team config read fails',
                    (service) =>
                        jest
                            .spyOn(service.teamWorkflowsConfigService, 'shouldCaptureEngagementEvents')
                            .mockRejectedValueOnce(new Error('column does not exist')),
                ],
            ])('still records the open when %s', async (_, fail) => {
                const parentRunId = new UUIDT().toString()
                fail(api['emailTrackingService'])
                const code = signer.generate({
                    functionId: hogFunction.id,
                    id: new UUIDT().toString(),
                    teamId: team.id,
                    parentRunId,
                    distinctId: 'distinct-id',
                })

                const response = await supertest(app).get(`/public/m/pixel?ph_id=${code}`)

                expect(response.status).toBe(200)
                await waitForExpect(() => {
                    const names = mockProducerObserver
                        .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                        .filter(({ value }) => value.app_source_id === parentRunId)
                        .map(({ value }) => value.metric_name)
                    expect(names.filter((name) => name === 'email_opened')).toHaveLength(1)
                })
            })

            it('counts a person once per run however often they open or click', async () => {
                const parentRunId = new UUIDT().toString()
                const phId = (id: string): string =>
                    signer.generate({
                        functionId: hogFunction.id,
                        id,
                        teamId: team.id,
                        parentRunId,
                    })
                const first = phId(new UUIDT().toString())
                const second = phId(new UUIDT().toString())

                for (const code of [first, first, second]) {
                    await supertest(app).get(`/public/m/pixel?ph_id=${code}`)
                }
                await supertest(app).get(`/public/m/redirect?ph_id=${first}&target=https://example.com`)
                await supertest(app).get(`/public/m/redirect?ph_id=${first}&target=https://example.com`)

                await waitForExpect(() => {
                    const counts: Record<string, number> = {}
                    for (const { value } of mockProducerObserver.getProducedKafkaMessagesForTopic(
                        KAFKA_APP_METRICS_2
                    )) {
                        if (value.app_source_id === parentRunId) {
                            counts[value.metric_name as string] =
                                (counts[value.metric_name as string] ?? 0) + (value.count as number)
                        }
                    }
                    expect(counts).toEqual({
                        email_opened: 3,
                        email_opened_by_person: 2,
                        email_link_clicked: 2,
                        email_clicked_by_person: 1,
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

        describe('SES webhook', () => {
            // The route enforces a real SNS signature; verifying it needs AWS's private key, so we
            // stub the check and let a posted SNS envelope flow through the real handler + service.
            let verifySignatureSpy: jest.SpyInstance
            let captureEngagementSpy: jest.SpyInstance
            let consumer: CdpSesWebhooksConsumer
            const allowedTopics = process.env.SES_ALLOWED_SNS_TOPIC_ARNS

            // The allowlist is read when the API starts, so a test that changes it restarts both.
            const startApiAndConsumer = (): void => {
                api = new CdpApi(hub, createCdpConsumerDeps(hub), {
                    hogQueue: createMockJobQueue(),
                    hogflowQueue: createMockJobQueue(),
                })
                app = setupExpressApp()
                app.use('/', api.router())
                server.close()
                server = app.listen(0, () => {})
                consumer = new CdpSesWebhooksConsumer(hub, createCdpConsumerDeps(hub))
            }

            beforeEach(() => {
                verifySignatureSpy = jest
                    .spyOn(SesWebhookHandler.prototype as any, 'verifySnsSignature')
                    .mockResolvedValue(true)
                captureEngagementSpy = jest.spyOn(TeamWorkflowsConfigService.prototype, 'shouldCaptureEngagementEvents')
                consumer = new CdpSesWebhooksConsumer(hub, createCdpConsumerDeps(hub))
            })

            afterEach(() => {
                verifySignatureSpy.mockRestore()
                captureEngagementSpy.mockRestore()
                if (allowedTopics === undefined) {
                    delete process.env.SES_ALLOWED_SNS_TOPIC_ARNS
                } else {
                    process.env.SES_ALLOWED_SNS_TOPIC_ARNS = allowedTopics
                }
            })

            const postBounce = async ({
                functionId,
                parentRunId,
                workflowVersion,
                transactionalMessageId,
                headerCode,
                distinctId,
                snsMessageId = new UUIDT().toString(),
                topicArn = 'arn:aws:sns:us-east-1:123456789012:ses-events',
                sesMessage,
                bounceType = 'Permanent',
                recipient = 'user@example.com',
            }: {
                functionId: string
                parentRunId?: string
                workflowVersion?: number
                // Sends the bounce as SES reports it for a transactional email with this message id.
                transactionalMessageId?: string
                headerCode?: string
                distinctId?: string
                snsMessageId?: string
                topicArn?: string
                sesMessage?: string
                bounceType?: 'Permanent' | 'Transient'
                recipient?: string
            }): Promise<supertest.Response> => {
                const trackingCode = signer.generate(
                    {
                        functionId,
                        id: transactionalMessageId ?? invocationId,
                        teamId: team.id,
                        parentRunId,
                        workflowVersion,
                        distinctId,
                    },
                    false,
                    workflowVersion !== undefined
                )
                const sesRecord = {
                    eventType: 'Bounce',
                    mail: {
                        timestamp: '2024-01-01T00:00:00.000Z',
                        source: 'sender@posthog.com',
                        messageId: 'ses-message-id',
                        destination: [recipient],
                        headers: [{ name: TRACKING_CODE_HEADER_NAME, value: headerCode ?? trackingCode }],
                        ...(transactionalMessageId
                            ? {
                                  commonHeaders: { to: [recipient] },
                                  tags: { ph_email_status: ['true'] },
                              }
                            : {}),
                    },
                    bounce: {
                        bounceType,
                        bouncedRecipients: [{ emailAddress: recipient }],
                        timestamp: '2024-01-01T00:00:00.000Z',
                    },
                }
                return await postEnvelope({
                    Type: 'Notification',
                    MessageId: snsMessageId,
                    TopicArn: topicArn,
                    Message: sesMessage ?? JSON.stringify(sesRecord),
                })
            }

            const postEnvelope = async (envelope: Record<string, string>): Promise<supertest.Response> => {
                return await supertest(app)
                    .post('/public/m/ses_webhook')
                    .set('Content-Type', 'text/plain')
                    .send(
                        JSON.stringify({
                            Timestamp: '2024-01-01T00:00:00.000Z',
                            SignatureVersion: '1',
                            Signature: 'stubbed',
                            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
                            ...envelope,
                        })
                    )
            }

            const recordBounce = async (bounce: Parameters<typeof postBounce>[0]): Promise<void> => {
                expect((await postBounce(bounce)).status).toBe(200)
                await consumer.processBatch(queuedSesNotifications())
            }

            const recordedMetrics = (): [string, number][] =>
                mockProducerObserver
                    .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    .map((m) => [m.value.metric_name as string, m.value.count as number])

            const bounceMetrics: [string, number][] = [
                ['email_bounced', 1],
                ['email_bounced_hard', 1],
            ]

            const sesTopicArn = 'arn:aws:sns:us-east-1:123456789012:ses-events'
            const otherTopicArn = 'arn:aws:sns:us-east-1:123456789012:other-topic'

            const rawMessage = (value: string): Message => ({
                ...createKafkaMessage(null),
                value: Buffer.from(value),
            })

            const queuedAtStage = async (stage: string): Promise<number> =>
                (await register.getSingleMetric('email_tracking_ses_queued_notifications_total')!.get()).values.find(
                    (v) => v.labels.stage === stage
                )?.value ?? 0

            it.each([
                ['on the replica', false, false],
                ['only on the primary, during replica lag', true, false],
                ['on the replica, while the hog function lookup fails', false, true],
                ['only on the primary, while the hog function lookup fails', true, true],
            ])('writes a hog_flow log entry for a bounce that resolves to a flow %s', async (_, lagging, fail) => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                if (lagging) {
                    hideHogFlowsFromReplica(hub.postgres, [hogFlow.id])
                }
                if (fail) {
                    jest.spyOn(
                        consumer['emailTrackingService']['hogFunctionManager'],
                        'getHogFunctions'
                    ).mockRejectedValue(new Error('hog function lookup failed'))
                }

                await recordBounce({ functionId: hogFlow.id })

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
                    app_source: 'hog_flow',
                    app_source_id: hogFlow.id,
                    metric_name: 'email_bounced',
                    metric_kind: 'email',
                })
            })

            it('counts a failed primary lookup as a lookup failure for a bounce on a flow only the primary has', async () => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                hideHogFlowsFromReplica(hub.postgres, [hogFlow.id])
                jest.spyOn(
                    consumer['emailTrackingService']['hogFlowManager'],
                    'getHogFlowsCheckingPrimaryOnMiss'
                ).mockRejectedValue(new Error('primary lookup failed'))
                const lookupFailures = async (): Promise<number> =>
                    (await register.getSingleMetric('email_tracking_errors_total')!.get()).values.find(
                        (v) => v.labels.error_type === 'hog_flow_lookup_failed' && v.labels.source === 'ses'
                    )?.value ?? 0
                const before = await lookupFailures()

                await recordBounce({ functionId: hogFlow.id })

                expect(await lookupFailures()).toBeGreaterThan(before)
                expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)).toHaveLength(0)
            })

            it('records the bounced status of a transactional email', async () => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                const messageId = new UUIDT().toString()

                await recordBounce({ functionId: hogFlow.id, transactionalMessageId: messageId })

                // Recording flushes the status row before the batch completes.
                expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_EMAIL_STATUS)).toEqual([
                    expect.objectContaining({
                        key: messageId,
                        value: expect.objectContaining({
                            team_id: team.id,
                            message_id: messageId,
                            status: 'bounced',
                            reason: 'hard',
                        }),
                    }),
                ])
            })

            it.each<[string, (service: any) => void]>([
                [
                    'reading the team config',
                    (service) =>
                        jest
                            .spyOn(service.teamWorkflowsConfigService, 'shouldCaptureEngagementEvents')
                            .mockRejectedValueOnce(new Error('column does not exist')),
                ],
                [
                    'queueing the engagement event',
                    (service) => {
                        jest.spyOn(
                            service.teamWorkflowsConfigService,
                            'shouldCaptureEngagementEvents'
                        ).mockResolvedValue(true)
                        jest.spyOn(service.capturedEventsService, 'queueEvent').mockRejectedValueOnce(
                            new Error('team lookup failed')
                        )
                    },
                ],
            ])(
                'fails the batch so Kafka redelivers it, and counts the notification once, when the first attempt fails %s',
                async (_, failFirstAttempt) => {
                    failFirstAttempt(consumer['emailTrackingService'])
                    expect((await postBounce({ functionId: hogFunction.id, distinctId: 'distinct-id' })).status).toBe(
                        200
                    )
                    const failedBefore = await queuedAtStage('failed')

                    await expect(consumer.processBatch(queuedSesNotifications())).rejects.toThrow()
                    expect(await queuedAtStage('failed')).toBe(failedBefore + 1)
                    await consumer.processBatch(queuedSesNotifications())

                    expect(recordedMetrics()).toEqual(bounceMetrics)
                }
            )

        describe('when a suppression write fails', () => {
            const failingConstraint = (): string => `test_fail_hard_bounce_${team.id}`

            const failHardBounceWrites = async (): Promise<void> => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `ALTER TABLE posthog_messagesuppression ADD CONSTRAINT ${failingConstraint()}
                     CHECK (team_id <> ${team.id} OR identifier <> 'hard@example.com') NOT VALID`,
                    [],
                    'test-fail-hard-bounce-writes'
                )
            }

            const fixHardBounceWrites = async (): Promise<void> => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `ALTER TABLE posthog_messagesuppression DROP CONSTRAINT IF EXISTS ${failingConstraint()}`,
                    [],
                    'test-fix-hard-bounce-writes'
                )
            }

            afterEach(fixHardBounceWrites)

            const suppressionRows = async (): Promise<
                { identifier: string; suppressed: boolean; transient_bounce_count: number }[]
            > =>
                (
                    await hub.postgres.query(
                        PostgresUse.COMMON_READ,
                        `SELECT identifier, suppressed, transient_bounce_count
                         FROM posthog_messagesuppression WHERE team_id = $1 ORDER BY identifier`,
                        [team.id],
                        'test-read-suppression'
                    )
                ).rows

            const writeFailures = async (outcome: string): Promise<number> =>
                (
                    await register.getSingleMetric('cdp_email_suppression_write_failures_total')!.get()
                ).values.find((v) => v.labels.write === 'hard_bounce' && v.labels.outcome === outcome)?.value ??
                0

            const queueHardAndSoftBounce = async (): Promise<Message[]> => {
                await postBounce({ functionId: hogFunction.id, recipient: 'hard@example.com' })
                await postBounce({
                    functionId: hogFunction.id,
                    recipient: 'soft@example.com',
                    bounceType: 'Transient',
                })
                return queuedSesNotifications()
            }

            it('fails the batch, and its redelivery suppresses each address once', async () => {
                hub.CDP_SES_SUPPRESSION_RETRY_TEAMS = String(team.id)
                startApiAndConsumer()
                const batch = await queueHardAndSoftBounce()
                await failHardBounceWrites()
                const retriedBefore = await writeFailures('retried')

                await expect(consumer.processBatch(batch)).rejects.toThrow('hard_bounce')
                await fixHardBounceWrites()
                await consumer.processBatch(batch)

                expect(await suppressionRows()).toEqual([
                    { identifier: 'hard@example.com', suppressed: true, transient_bounce_count: 0 },
                    { identifier: 'soft@example.com', suppressed: false, transient_bounce_count: 1 },
                ])
                expect(await writeFailures('retried')).toBe(retriedBefore + 1)
            })

            it('drops the write and counts it for a team outside the retry switch', async () => {
                const batch = await queueHardAndSoftBounce()
                await failHardBounceWrites()
                const droppedBefore = await writeFailures('dropped')

                await consumer.processBatch(batch)

                expect(await suppressionRows()).toEqual([
                    { identifier: 'soft@example.com', suppressed: false, transient_bounce_count: 1 },
                ])
                expect(await writeFailures('dropped')).toBe(droppedBefore + 1)
            })
        })

            it('answers 200 and queues the envelope by its MessageId without recording it', async () => {
                const snsMessageId = new UUIDT().toString()

                const res = await postBounce({ functionId: hogFunction.id, snsMessageId })

                expect(res.status).toBe(200)
                const queued = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_CDP_SES_WEBHOOKS)
                expect(queued).toEqual([
                    expect.objectContaining({
                        key: snsMessageId,
                        value: expect.objectContaining({ Type: 'Notification', MessageId: snsMessageId }),
                    }),
                ])
                expect(recordedMetrics()).toEqual([])
            })

            it('answers 403 and queues nothing when the signature is invalid', async () => {
                verifySignatureSpy.mockResolvedValue(false)

                const res = await postBounce({ functionId: hogFunction.id })

                expect(res.status).toBe(403)
                expect(queuedSesNotifications()).toEqual([])
            })

            it('answers 403 and queues nothing for a topic outside the allowlist', async () => {
                process.env.SES_ALLOWED_SNS_TOPIC_ARNS = sesTopicArn
                startApiAndConsumer()

                const res = await postBounce({ functionId: hogFunction.id, topicArn: otherTopicArn })

                expect(res.status).toBe(403)
                expect(queuedSesNotifications()).toEqual([])
            })

            it('confirms a subscription on the request and queues nothing', async () => {
                const subscribeUrl = 'https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&Token=t'

                const res = await postEnvelope({
                    Type: 'SubscriptionConfirmation',
                    MessageId: new UUIDT().toString(),
                    Token: 't',
                    TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                    Message: 'You have chosen to subscribe to the topic.',
                    SubscribeURL: subscribeUrl,
                })

                expect(res.status).toBe(200)
                expect(mockFetch).toHaveBeenCalledWith(subscribeUrl)
                expect(queuedSesNotifications()).toEqual([])
            })

            it('answers 500 so SNS retries when the produce fails', async () => {
                mockProducerObserver.produceSpy.mockRejectedValueOnce(new Error('broker unavailable'))

                const res = await postBounce({ functionId: hogFunction.id })

                expect(res.status).toBe(500)
            })

            it('produces the metrics and logs of a whole batch in one flush before the batch resolves', async () => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                for (let i = 0; i < 3; i++) {
                    await postBounce({ functionId: hogFlow.id })
                }
                const flush = jest.spyOn(consumer['emailTrackingService']['hogFunctionMonitoringService'], 'flush')

                await consumer.processBatch(queuedSesNotifications())

                expect(flush).toHaveBeenCalledTimes(1)
                expect(recordedMetrics()).toEqual([
                    ['email_bounced', 3],
                    ['email_bounced_hard', 3],
                ])
                expect(mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)).toHaveLength(3)
            })

            it('fails the batch so Kafka redelivers it when the flush fails', async () => {
                await postBounce({ functionId: hogFunction.id })
                jest.spyOn(
                    consumer['emailTrackingService']['hogFunctionMonitoringService'],
                    'flush'
                ).mockRejectedValueOnce(new Error('broker unavailable'))

                await expect(consumer.processBatch(queuedSesNotifications())).rejects.toThrow('broker unavailable')
            })

            it('flushes the notifications that recorded before it fails the batch', async () => {
                const parentRunId = new UUIDT().toString()
                await postEnvelope({
                    Type: 'Notification',
                    MessageId: new UUIDT().toString(),
                    TopicArn: sesTopicArn,
                    Message: JSON.stringify({
                        eventType: 'Open',
                        mail: {
                            timestamp: '2024-01-01T00:00:00.000Z',
                            source: 'sender@posthog.com',
                            messageId: 'ses-message-id',
                            destination: ['user@example.com'],
                            headers: [
                                {
                                    name: TRACKING_CODE_HEADER_NAME,
                                    value: signer.generate({
                                        functionId: hogFunction.id,
                                        id: new UUIDT().toString(),
                                        teamId: team.id,
                                        parentRunId,
                                    }),
                                },
                            ],
                        },
                        open: { timestamp: '2024-01-01T00:00:00.000Z' },
                    }),
                })
                const failingId = new UUIDT().toString()
                await postBounce({ functionId: hogFunction.id, snsMessageId: failingId })
                const service = consumer['emailTrackingService']
                const record = service.recordQueuedSesNotification.bind(service)
                jest.spyOn(service, 'recordQueuedSesNotification').mockImplementation((envelope) =>
                    envelope.MessageId === failingId ? Promise.reject(new Error('datastore down')) : record(envelope)
                )

                await expect(consumer.processBatch(queuedSesNotifications())).rejects.toThrow('datastore down')

                expect(recordedMetrics()).toEqual([
                    ['email_opened', 1],
                    ['email_opened_by_person', 1],
                ])
            })

            it('records at most 10 notifications at a time and starts none after one fails', async () => {
                const pending: { resolve: (skip: null) => void; reject: (error: Error) => void }[] = []
                jest.spyOn(consumer as any, 'record').mockImplementation(
                    () => new Promise((resolve, reject) => pending.push({ resolve, reject }))
                )
                const flush = jest.spyOn(consumer['emailTrackingService'], 'flush')
                let settled = false
                const batch = consumer
                    .processBatch(Array.from({ length: 25 }, () => createKafkaMessage(null)))
                    .finally(() => {
                        settled = true
                    })
                const tick = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

                await tick()
                expect(pending).toHaveLength(10)

                pending[0].resolve(null)
                await tick()
                expect(pending).toHaveLength(11)

                pending[1].reject(new Error('datastore down'))
                await tick()
                expect(pending).toHaveLength(11)
                expect(settled).toBe(false)
                expect(flush).not.toHaveBeenCalled()

                pending.slice(2).forEach(({ resolve }) => resolve(null))
                await expect(batch).rejects.toThrow('datastore down')
                expect(pending).toHaveLength(11)
                expect(flush).toHaveBeenCalledTimes(1)
            })

            it('queues a sensitive email click without its subject or link secrets and still records it', async () => {
                const trackingCode = signer.generate({
                    functionId: hogFunction.id,
                    id: invocationId,
                    teamId: team.id,
                })
                const subject = 'Your login code is 482913'
                await postEnvelope({
                    Type: 'Notification',
                    MessageId: new UUIDT().toString(),
                    TopicArn: sesTopicArn,
                    Message: JSON.stringify({
                        eventType: 'Click',
                        mail: {
                            timestamp: '2024-01-01T00:00:00.000Z',
                            source: 'sender@posthog.com',
                            messageId: 'ses-message-id',
                            destination: ['user@example.com'],
                            headers: [
                                { name: TRACKING_CODE_HEADER_NAME, value: trackingCode },
                                { name: 'Subject', value: subject },
                            ],
                            commonHeaders: { subject },
                            tags: { ph_sensitive: ['true'] },
                        },
                        click: {
                            link: 'https://app.example.com/reset/Xk3pR9mQ2a?token=s3cret',
                            timestamp: '2024-01-01T00:00:00.000Z',
                        },
                    }),
                })

                const queued = queuedSesNotifications()
                const queuedValue = queued.map((m) => m.value?.toString()).join()
                expect(queuedValue).not.toContain('482913')
                expect(queuedValue).not.toContain('s3cret')
                expect(queuedValue).not.toContain('Xk3pR9mQ2a')

                await consumer.processBatch(queued)

                const clicks = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(clicks.map((m) => [m.value.metric_name, m.value.count])).toEqual([['email_link_clicked', 1]])
            })

            it.each<[string, () => Promise<Message>]>([
                ['is not JSON', () => Promise.resolve(rawMessage('not json'))],
                ['is not an SNS envelope', () => Promise.resolve(rawMessage('{}'))],
                [
                    'fails the SES event schema',
                    async () => {
                        await postBounce({
                            functionId: hogFunction.id,
                            sesMessage: JSON.stringify({ eventType: 'Bounce' }),
                        })
                        return queuedSesNotifications()[0]
                    },
                ],
                [
                    'recording rejects',
                    async () => {
                        await postBounce({ functionId: hogFunction.id, topicArn: otherTopicArn })
                        process.env.SES_ALLOWED_SNS_TOPIC_ARNS = sesTopicArn
                        startApiAndConsumer()
                        return queuedSesNotifications()[0]
                    },
                ],
            ])('skips a message that %s and records the rest of the batch', async (_, failingMessage) => {
                const failing = await failingMessage()
                await postBounce({ functionId: hogFunction.id })
                const recordable = queuedSesNotifications().at(-1)!
                const skippedBefore = await queuedAtStage('skipped')

                await consumer.processBatch([failing, recordable])

                expect(recordedMetrics()).toEqual(bounceMetrics)
                expect(await queuedAtStage('skipped')).toBe(skippedBefore + 1)
            })

            it('records the metric but writes no log entry and reads no workflow from the primary when the bounce resolves to a hog_function', async () => {
                const query = jest.spyOn(hub.postgres, 'query')

                await recordBounce({ functionId: hogFunction.id })

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
                expect(
                    query.mock.calls.filter(
                        ([target, , , tag]) => target === PostgresUse.COMMON_WRITE && tag === 'fetchHogFlows'
                    )
                ).toHaveLength(0)
            })

            it('attributes the bounce to the version that sent it, not the version live when it lands', async () => {
                // The workflow has been republished since the send. Reading the version off the flow
                // manager here would blame v5 for v2's bounce — which is precisely the comparison
                // ("did the new version bounce more?") the versioned series exists to answer.
                const hogFlow = await insertHogFlow(hub.postgres, {
                    ...new FixtureHogFlowBuilder().withTeamId(team.id).build(),
                    version: 5,
                })

                await recordBounce({ functionId: hogFlow.id, workflowVersion: 2 })

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

            const sendEmail = async ({
                teamCaptures,
                captureEngagement,
                transactional = false,
            }: {
                teamCaptures: boolean
                captureEngagement?: boolean
                transactional?: boolean
            }): Promise<{ hogFlowId: string; headerCode: string; tags: Record<string, string[]> }> => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO workflows_teamworkflowsconfig
                        (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                         email_sending_suspension_reason, ses_tenant_sending_status, email_sending_tier)
                     VALUES ($1, $2, 'off', '', '', 0)`,
                    [team.id, teamCaptures],
                    'test-set-engagement-capture'
                )
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                const integration = await insertIntegration(hub.postgres, team.id, {
                    kind: 'email',
                    config: {
                        email: 'sender@posthog-test.com',
                        name: 'Sender',
                        domain: 'posthog-test.com',
                        verified: true,
                        provider: 'ses',
                    },
                })
                const emailService = api['hogExecutorAsync']['deps'].emailService
                const sesSend = jest
                    .spyOn(emailService.sesV2Client!, 'send')
                    .mockResolvedValue({ MessageId: 'ses-message-id' } as never)
                const invocation = createExampleInvocation({ id: hogFlow.id, team_id: team.id })
                invocation.state.globals.event.distinct_id = 'user-1'
                if (transactional) {
                    invocation.state.globals.event.event = TRANSACTIONAL_EMAIL_EVENT
                }
                if (captureEngagement !== undefined) {
                    invocation.state.send = { tracking: { captureEngagement } }
                }
                invocation.queueParameters = {
                    type: 'email',
                    to: { email: 'user@example.com', name: 'User' },
                    from: { integrationId: integration.id },
                    subject: 'Reset your password',
                    text: 'Hi',
                    html: '<p>Hi</p>',
                }

                expect((await emailService.executeSendEmail(invocation)).error).toBeUndefined()
                const input = (sesSend.mock.calls[0][0] as any).input
                const headers: { Name: string; Value: string }[] = input.Content.Simple.Headers
                const emailTags: { Name: string; Value: string }[] = input.EmailTags
                mockInternalFetch.mockClear()
                return {
                    hogFlowId: hogFlow.id,
                    headerCode: headers.find((header) => header.Name === TRACKING_CODE_HEADER_NAME)!.Value,
                    tags: Object.fromEntries(emailTags.map((tag) => [tag.Name, [tag.Value]])),
                }
            }

            it.each([
                { captureEngagement: true, teamCaptures: true, captured: 1 },
                { captureEngagement: undefined, teamCaptures: true, captured: 1 },
                { captureEngagement: false, teamCaptures: true, captured: 0 },
                { captureEngagement: true, teamCaptures: false, captured: 0 },
            ])(
                "captures the bounce of a sent email by the send's choice $captureEngagement and the team switch $teamCaptures",
                async ({ captureEngagement, teamCaptures, captured }) => {
                    const { hogFlowId, headerCode } = await sendEmail({ teamCaptures, captureEngagement })

                    await recordBounce({ functionId: hogFlowId, headerCode })

                    const capturedEvents = mockInternalFetch.mock.calls.map(
                        ([, options]) => parseJSON(String(options?.body)).event
                    )
                    expect(capturedEvents.filter((event) => event === '$workflows_email_bounced')).toHaveLength(
                        captured
                    )
                }
            )

            it.each([
                ['a transactional email', true],
                ['an email from a workflow step', false],
            ])(
                'marks the delivery of %s as transactional only for a transactional send',
                async (_name, transactional) => {
                    const { headerCode, tags } = await sendEmail({ teamCaptures: true, transactional })

                    const res = await postEnvelope({
                        Type: 'Notification',
                        MessageId: new UUIDT().toString(),
                        TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-events',
                        Message: JSON.stringify({
                            eventType: 'Delivery',
                            mail: {
                                timestamp: '2024-01-01T00:00:00.000Z',
                                source: 'sender@posthog-test.com',
                                messageId: 'ses-message-id',
                                destination: ['user@example.com'],
                                headers: [{ name: TRACKING_CODE_HEADER_NAME, value: headerCode }],
                                tags,
                            },
                            delivery: { timestamp: '2024-01-01T00:05:00.000Z', recipients: ['user@example.com'] },
                        }),
                    })
                    expect(res.status).toBe(200)
                    await consumer.processBatch(queuedSesNotifications())

                    const captured = mockInternalFetch.mock.calls.map(([, options]) => parseJSON(String(options?.body)))
                    expect(captured.map((event) => [event.event, event.timestamp])).toEqual([
                        ['$workflows_email_delivered', '2024-01-01T00:05:00.000Z'],
                    ])
                    expect(captured[0].properties.$email_transactional).toEqual(transactional ? true : undefined)
                }
            )

            it('captures the bounce event with the send it came from', async () => {
                captureEngagementSpy.mockResolvedValue(true)
                const hogFlow = await insertHogFlow(hub.postgres, {
                    ...new FixtureHogFlowBuilder().withTeamId(team.id).build(),
                    version: 5,
                })

                await recordBounce({ functionId: hogFlow.id, workflowVersion: 2, distinctId: 'user-1' })

                await waitForExpect(() => {
                    const captured = mockInternalFetch.mock.calls.map(([, options]) => parseJSON(options.body))
                    expect(captured).toHaveLength(1)
                    expect(captured[0]).toMatchObject({
                        event: '$workflows_email_bounced',
                        distinct_id: 'user-1',
                        properties: {
                            $workflow_id: hogFlow.id,
                            $workflow_invocation_id: invocationId,
                            $workflow_version: 2,
                            $email_message_id: 'ses-message-id',
                        },
                    })
                })
            })

            it('keys the log entry under parentRunId for batch-triggered runs', async () => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                const parentRunId = 'batch-run-id'

                await recordBounce({ functionId: hogFlow.id, parentRunId })

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
        let consumer: CdpSesWebhooksConsumer

        beforeEach(() => {
            hub.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = 1
            hub.CDP_EMAIL_SOFT_BOUNCE_EVENT_TIME_TEAMS = String(team.id)

            api = new CdpApi(hub, createCdpConsumerDeps(hub), {
                hogQueue: createMockJobQueue(),
                hogflowQueue: createMockJobQueue(),
            })
            app = setupExpressApp()
            app.use('/', api.router())
            server = app.listen(0, () => {})
            consumer = new CdpSesWebhooksConsumer(hub, createCdpConsumerDeps(hub))

            verifySignatureSpy = jest
                .spyOn(SesWebhookHandler.prototype as any, 'verifySnsSignature')
                .mockResolvedValue(true)
        })

        afterEach(() => {
            server.close()
            verifySignatureSpy.mockRestore()
        })

        const deliver = async (envelope: Record<string, string>): Promise<supertest.Response> => {
            const res = await supertest(app)
                .post('/public/m/ses_webhook')
                .set('Content-Type', 'text/plain')
                .send(JSON.stringify(envelope))
            await consumer.processBatch(queuedSesNotifications())
            return res
        }

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
            return await deliver(envelope)
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
            return await deliver(envelope)
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
            return await deliver(envelope)
        }

        it('inserts a suppression row and marks it suppressed after a Transient bounce webhook', async () => {
            const hogFlow = await insertHogFlow(hub.postgres, new FixtureHogFlowBuilder().withTeamId(team.id).build())
            const email = 'transient-bouncer@example.com'

            const res = await postTransientBounce(hogFlow.id, email)
            expect(res.status).toBe(200)

            // Recording awaits the suppression write, so the row is present once the batch
            // completes — no waitForExpect needed.
            const result = await hub.postgres.query<{
                identifier: string
                source: string
                suppressed: boolean
                transient_bounce_count: number
                deleted: boolean
                last_bounce_at: string
            }>(
                PostgresUse.COMMON_READ,
                `SELECT identifier, source, suppressed, transient_bounce_count, deleted, last_bounce_at
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
                    last_bounce_at: '2024-01-01T00:00:00.000Z',
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

        // The webhook write and the pre-send read are covered separately. This joins them end to end:
        // a real SES envelope over the HTTP route, then the check every email step runs before sending.
        // It fails if a Permanent bounce stops marking the row, which would keep sending transactional
        // email to a dead address, or if a soft bounce or complaint starts marking it, which would drop
        // invoices and password resets for a working address.
        it.each([
            ['a transient bounce', postTransientBounce, false],
            ['a complaint', postComplaint, false],
            ['a permanent bounce', postPermanentBounce, true],
        ] as const)(
            '%s suppresses marketing email, and blocks transactional email only for a hard bounce',
            async (_label, postWebhook, blocksTransactional) => {
                const hogFlow = await insertHogFlow(
                    hub.postgres,
                    new FixtureHogFlowBuilder().withTeamId(team.id).build()
                )
                const email = 'send-decision@example.com'

                const res = await postWebhook(hogFlow.id, email)
                expect(res.status).toBe(200)

                const suppression = new EmailSuppressionService(hub.postgres, {
                    transientBounceThreshold: hub.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD,
                })

                expect(await suppression.isSuppressed(team.id, email)).toBe(true)
                expect(await suppression.isSuppressed(team.id, email, { transactional: true })).toBe(
                    blocksTransactional
                )
            }
        )
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
