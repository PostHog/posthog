import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { MessageRejected, SendingPausedException, TooManyRequestsException } from '@aws-sdk/client-sesv2'

import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { selectEmailSenderIntegrationId } from './email-sender-selection'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from './email-suppression.service'
import { EmailService, parseAddressList, sanitizeEmailSubject, teamEmailCapBuckets } from './email.service'
import { MailDevAPI } from './helpers/maildev'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

class ThrottlingException extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ThrottlingException'
    }
}

describe('sanitizeEmailSubject', () => {
    it.each([
        ['passes through normal text', 'Hello World', 'Hello World'],
        ['strips null bytes', 'Hello\x00World', 'HelloWorld'],
        ['replaces newlines with space', 'Hello\r\nWorld', 'Hello World'],
        ['replaces lone CR with space', 'Hello\rWorld', 'Hello World'],
        ['replaces lone LF with space', 'Hello\nWorld', 'Hello World'],
        ['strips control chars (BEL, BS, ESC)', 'He\x07ll\x08o\x1BWorld', 'HelloWorld'],
        ['strips DEL character', 'Hello\x7FWorld', 'HelloWorld'],
        ['preserves horizontal tab', 'Hello\tWorld', 'Hello\tWorld'],
        ['trims leading/trailing whitespace', '  Hello World  ', 'Hello World'],
        [
            'collapses multiple newlines into single space',
            'Hello \\ \ goodbye rn\r\n\r\nn ¯\_(ツ)_/¯',
            'Hello \\  goodbye rn n ¯\_(ツ)_/¯',
        ],
        ['handles mixed control chars and newlines', '\x00Hello\r\n\x07World\x1B', 'Hello World'],
        ['preserves unicode characters', 'Héllo Wörld 🎉', 'Héllo Wörld 🎉'],
        ['preserves email-typical special chars', 'Re: Your order #1234 — 50% off!', 'Re: Your order #1234 — 50% off!'],
    ])('%s', (_name, input, expected) => {
        expect(sanitizeEmailSubject(input)).toEqual(expected)
    })
})

describe('parseAddressList', () => {
    it.each([
        ['clean input', 'a@b.com, c@d.com', ['a@b.com', 'c@d.com']],
        ['extra spaces', '  a@b.com ,  c@d.com  ', ['a@b.com', 'c@d.com']],
        ['trailing comma', 'a@b.com, c@d.com,', ['a@b.com', 'c@d.com']],
    ])('%s', (_name, input, expected) => {
        expect(parseAddressList(input)).toEqual(expected)
    })

    it('should return undefined for empty values', () => {
        expect(parseAddressList(undefined)).toBeUndefined()
        expect(parseAddressList('')).toBeUndefined()
        expect(parseAddressList(',')).toBeUndefined()
    })
})

let integrationIdBase: number

const getIntegrationId = (id: number): number => integrationIdBase + id

const createEmailParams = (
    params: Partial<CyclotronInvocationQueueParametersEmailType> = {}
): CyclotronInvocationQueueParametersEmailType => {
    const from = params.from ?? { integrationId: 1 }
    return {
        type: 'email',
        to: { email: 'test@example.com', name: 'Test User' },
        subject: 'Test Subject',
        text: 'Test Text',
        html: 'Test HTML',
        ...params,
        from: {
            ...from,
            integrationId: getIntegrationId(from.integrationId),
            integrationIds: from.integrationIds?.map(getIntegrationId),
        },
    }
}
describe('EmailService', () => {
    let service: EmailService
    let hub: Hub
    let team: Team
    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team
        integrationIdBase = team.id
        service = new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
                sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
            new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
            new RecipientsManagerService(hub.postgres)
        )
        mockFetch.mockClear()
    })
    afterEach(async () => {
        await closeHub(hub)
    })
    describe('when SES is not configured', () => {
        it('should not crash on construction and should fail explicitly on send', async () => {
            const serviceWithoutSES = new EmailService(
                {
                    sesAccessKeyId: '',
                    sesSecretAccessKey: '',
                    sesRegion: '',
                    sesEndpoint: '',
                    sesTrackedConfigurationSet: 'posthog-messaging',
                    sesUntrackedConfigurationSet: '',
                },
                hub.integrationManager,
                new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
                hub.ENCRYPTION_SALT_KEYS,
                hub.SITE_URL,
                new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                new RecipientsManagerService(hub.postgres)
            )
            expect(serviceWithoutSES.sesV2Client).toBeNull()

            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog.com',
                    name: 'Test User',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'ses',
                },
            })
            const invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = { stack: [] } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1 } })

            const result = await serviceWithoutSES.executeSendEmail(invocation)
            expect(result.error).toBe('SES is not configured - set SES_REGION and AWS credentials')
        })
    })

    describe('executeSendEmail', () => {
        let invocation: CyclotronJobInvocationHogFunction
        let sendEmailSpy: jest.SpyInstance
        beforeEach(async () => {
            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog.com',
                    name: 'Test User',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'ses',
                },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = {
                stack: [],
            } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1 } })

            // Mock SES v2 send to avoid actual AWS calls
            sendEmailSpy = jest.spyOn(service.sesV2Client!, 'send') as any
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
        })
        describe('integration validation', () => {
            beforeEach(async () => {
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(2),
                    kind: 'email',
                    config: {
                        email: 'test@other-domain.com',
                        name: 'Test User',
                        domain: 'other-domain.com',
                        verified: false,
                    },
                })
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(3),
                    kind: 'slack',
                    config: {},
                })
            })
            it('should validate if the integration is not found', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 100 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(
                    `"Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step."`
                )
            })
            it('should validate if the integration is not an email integration', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 3 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(
                    `"The integration configured for this step is not an email channel — select an email sender in the workflow's email step."`
                )
            })
            it('should validate if the integration is not the correct team', async () => {
                invocation.teamId = 100
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(
                    `"Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step."`
                )
            })
            it('should validate if the email domain is not verified', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 2 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"The selected email integration domain is not verified"`)
            })
            it('should send identical from and feedback forwarding args', async () => {
                // This test is important for spam classification - feedback forwarding email MUST match from email
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalled()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe('"Test User" <test@posthog.com>')
                expect(sentCommand.input.FeedbackForwardingEmailAddress).toBe('test@posthog.com')
            })
            it('should allow a valid email integration and domain', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
            })

            it('uses and logs the sender selected for this workflow invocation', async () => {
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(4),
                    kind: 'email',
                    config: {
                        email: 'second@posthog.com',
                        name: 'Second Sender',
                        domain: 'posthog.com',
                        verified: true,
                        provider: 'ses',
                    },
                })
                invocation.id = Array.from({ length: 10 }, (_, index) => `invocation-${index}`).find(
                    (id) =>
                        selectEmailSenderIntegrationId(id, {
                            integrationId: getIntegrationId(1),
                            integrationIds: [getIntegrationId(1), getIntegrationId(4)],
                        }) === getIntegrationId(4)
                )!
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, integrationIds: [1, 4] },
                })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe('"Second Sender" <second@posthog.com>')
                expect(result.logs.map((log) => log.message)).toContain(
                    'Email sent to test@example.com from Second Sender <second@posthog.com>'
                )
            })
        })
        describe('from overrides', () => {
            it.each<[string, { email?: string; name?: string }, string, string]>([
                [
                    'address on the verified domain',
                    { email: 'community@posthog.com' },
                    '"Test User" <community@posthog.com>',
                    'community@posthog.com',
                ],
                [
                    'address with different domain casing',
                    { email: 'community@POSTHOG.com' },
                    '"Test User" <community@POSTHOG.com>',
                    'community@POSTHOG.com',
                ],
                ['name only', { name: 'Community Team' }, '"Community Team" <test@posthog.com>', 'test@posthog.com'],
                [
                    'name and address',
                    { email: 'community@posthog.com', name: 'Community Team' },
                    '"Community Team" <community@posthog.com>',
                    'community@posthog.com',
                ],
                [
                    'empty overrides fall back to the integration sender',
                    { email: '', name: '' },
                    '"Test User" <test@posthog.com>',
                    'test@posthog.com',
                ],
                [
                    'name with header-breaking characters is sanitized',
                    { name: '"Evil" <fake@evil.com>,\r\n Bcc:' },
                    '"Evil fake@evil.com, Bcc:" <test@posthog.com>',
                    'test@posthog.com',
                ],
            ])('applies the %s', async (_desc, fromOverride, expectedFrom, expectedFeedback) => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, ...fromOverride },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe(expectedFrom)
                expect(sentCommand.input.FeedbackForwardingEmailAddress).toBe(expectedFeedback)
            })

            it.each([
                ['an address on an unverified domain', 'someone@evil.com'],
                ['an address on a subdomain of the verified domain', 'someone@sub.posthog.com'],
                ['a list of addresses', 'a@posthog.com, b@posthog.com'],
                ['an RFC-822 formatted address', '"Name" <a@posthog.com>'],
                ['a value that is not an email address', 'not-an-email'],
            ])('discards %s and sends from the integration sender', async (_desc, email) => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, email },
                })
                const result = await service.executeSendEmail(invocation)
                // Failing the send would break every step still carrying the placeholder address
                // an old sender picker wrote, so an unusable override degrades to the integration's
                // own sender. The unverified address must never reach the provider either way.
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe('"Test User" <test@posthog.com>')
                expect(result.logs.some((log) => log.level === 'warn' && log.message.includes(email))).toBe(true)
            })
        })
        describe('email sending', () => {
            it('should send an email', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalled()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input).toMatchObject({
                    FromEmailAddress: '"Test User" <test@posthog.com>',
                    FeedbackForwardingEmailAddress: 'test@posthog.com',
                    Destination: {
                        ToAddresses: ['"Test User" <test@example.com>'],
                    },
                    Content: {
                        Simple: {
                            Subject: {
                                Data: 'Test Subject',
                            },
                            Body: {
                                Text: {
                                    Data: 'Test Text',
                                },
                            },
                        },
                    },
                })
            })
        })
        describe('SES throttle handling', () => {
            // SES throttle responses become reschedule-with-backoff rather than
            // permanent failures. The local Valkey bucket already gates dequeue;
            // this path is the safety net for when SES disagrees with our estimate.
            // Retryable: TooManyRequestsException (SES v2's rate-limit class) and
            // ThrottlingException (generic AWS SDK throttle name surfaced from
            // the transport layer). SendingPausedException is *not* retryable —
            // it signals a reputation/account-state issue that needs operator
            // attention, not a 500ms reschedule.
            const throttleCases: Array<[string, () => Error]> = [
                [
                    'TooManyRequestsException',
                    () => new TooManyRequestsException({ $metadata: {}, message: 'Too many requests' }),
                ],
                ['ThrottlingException', () => new ThrottlingException('Rate exceeded')],
            ]
            it.each(throttleCases)('reschedules instead of failing when SES returns %s', async (_name, makeError) => {
                sendEmailSpy.mockRejectedValueOnce(makeError())

                const before = Date.now()
                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                // Jittered 500–1000ms retry: must land in the future but never further
                // than the upper bound + scheduler overhead.
                expect(scheduledMs).toBeGreaterThanOrEqual(before + 400)
                expect(scheduledMs).toBeLessThan(before + 2000)
                // No business metric emitted on throttle — the eventual retry
                // will produce email_sent.
                expect(result.metrics ?? []).toEqual([])
            })

            it('keeps the send priority class across a throttle reschedule', async () => {
                // A bulk send enters the email queue at priority 1. On an SES throttle the job is
                // rescheduled on the email queue, so its priority must stay 1 — resetting it to the
                // fast-lane value 0 would let throttled bulk bursts jump ahead of transactional sends,
                // which is exactly the traffic the fast lane exists to protect.
                invocation.queuePriority = 1
                sendEmailSpy.mockRejectedValueOnce(
                    new TooManyRequestsException({ $metadata: {}, message: 'Too many requests' })
                )

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                expect(result.invocation.queuePriority).toBe(1)
            })

            it('hard-fails (not retry) when SES returns SendingPausedException', async () => {
                // Reputation/account-state pause won't recover in 500ms; retrying
                // just burns reschedules. Hard-fail so the failure surfaces via
                // email_failed and an operator can investigate.
                sendEmailSpy.mockRejectedValueOnce(
                    new SendingPausedException({ $metadata: {}, message: 'Sending paused' })
                )

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toMatch(/Failed to send email via SES: Sending paused/)
                expect(result.metrics).toEqual(
                    expect.arrayContaining([expect.objectContaining({ metric_name: 'email_failed' })])
                )
            })

            it('still fails the job for non-throttle SES errors', async () => {
                sendEmailSpy.mockRejectedValueOnce(
                    new MessageRejected({ $metadata: {}, message: 'something else broke' })
                )

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toMatch(/Failed to send email via SES: something else broke/)
                // Business metric should record the failure.
                expect(result.metrics).toEqual(
                    expect.arrayContaining([expect.objectContaining({ metric_name: 'email_failed' })])
                )
            })
        })

        describe('workflow sending rate limit', () => {
            let claimOrReserve: jest.Mock
            let limitedService: EmailService
            let limitedSendSpy: jest.SpyInstance

            beforeEach(() => {
                claimOrReserve = jest.fn().mockResolvedValue({ granted: 1, retryAfterMs: null, reserved: false })
                limitedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                    },
                    hub.integrationManager,
                    new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    { claimOrReserve } as unknown as RateLimiterService
                )
                limitedSendSpy = jest.spyOn(limitedService.sesV2Client!, 'send') as any
                limitedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.hogFunction.metadata = {
                    email_sending_rate_limit: { count: 120, period: 'minute' },
                }
            })

            it.each([
                // A reserved slot means "your turn is at this exact time". Park on it as-is:
                // wake earlier and the token is not there yet, so the send gets denied again
                // and goes to the back of the line.
                ['exactly at the reserved slot', 5000, true, 5000, 5000],
                // Sub-second slots too: flooring them to 1s would push the wake off its
                // slot and collide it with the slot behind.
                ['exactly at a sub-second reserved slot', 500, true, 500, 500],
                // Past the horizon there are no slots left and everyone gets the same "come
                // back in an hour", so those wakes get spread out (1x-2x) instead.
                [
                    'with spread when re-contending at the horizon',
                    60 * 60 * 1000,
                    false,
                    60 * 60 * 1000,
                    2 * 60 * 60 * 1000,
                ],
                // No horizon at all (error-path denial) falls back to the clamped token
                // interval: 120/minute refills every 500ms, clamped to [1s, 2s] jittered.
                ['on the clamped token interval when the limiter could not reserve', null, false, 1000, 2000],
            ])('reschedules a denied send %s', async (_name, retryAfterMs, reserved, minDelayMs, maxDelayMs) => {
                claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs, reserved })

                const before = Date.now()
                const result = await limitedService.executeSendEmail(invocation)
                const after = Date.now()

                expect(limitedSendSpy).not.toHaveBeenCalled()
                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                // The reschedule must carry the email payload forward: without queueParameters the
                // retry has nothing to send and the throttled email is dropped rather than delayed.
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                // Bracketed against both ends of the call, so the bounds hold the delay itself
                // and not the time the call took.
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + minDelayMs)
                expect(scheduledMs).toBeLessThanOrEqual(after + maxDelayMs)
                // No business metric on a pacing delay — the eventual send produces email_sent.
                expect(result.metrics ?? []).toEqual([])
            })

            it('parks consecutive denials on their exact reserved slots', async () => {
                // At 30/minute the limiter hands out slots 2s apart. Each send has to wake at
                // its own slot, exactly. If one wake moves even a little earlier, its token is
                // not there yet and the send goes to the back of the line.
                invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 30, period: 'minute' } }
                const slotMs = 2000

                for (let i = 1; i <= 3; i++) {
                    claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: i * slotMs, reserved: true })

                    const before = Date.now()
                    const denied = await limitedService.executeSendEmail(invocation)
                    const after = Date.now()

                    expect(denied.finished).toBe(false)
                    const parkedAt = denied.invocation.queueScheduledAt!.toMillis()
                    expect(parkedAt).toBeGreaterThanOrEqual(before + i * slotMs)
                    expect(parkedAt).toBeLessThanOrEqual(after + i * slotMs)
                }
            })

            it('scatters a backlog that overflows the reservation horizon', async () => {
                // When the backlog is deeper than one hour of refill there are no slots left:
                // every remaining send gets "come back in an hour". If they all came back at
                // the same moment they would pile up at the front of the queue again, so their
                // wakes get spread out over the hour.
                claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: 60 * 60 * 1000, reserved: false })

                const parkedAt: number[] = []
                for (let i = 0; i < 20; i++) {
                    const denied = await limitedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }

                // The wakes must cover a real part of the hour, not one narrow window:
                // 20 of them spread over an hour should easily span more than 10 minutes.
                const spreadMs = Math.max(...parkedAt) - Math.min(...parkedAt)
                expect(spreadMs).toBeGreaterThan(10 * 60 * 1000)
            })

            it('claims one token scoped to the workflow and sends when granted', async () => {
                const result = await limitedService.executeSendEmail(invocation)

                expect(claimOrReserve).toHaveBeenCalledWith(
                    {
                        key: `@posthog/workflow-email-rate/${team.id}/function-1`,
                        requested: 1,
                        // Burst capacity is ~1s of budget (not the count), so the first period can't
                        // send ~2x the limit and an idle-expired bucket can't re-burst.
                        capacity: 2,
                        refillPerSecond: 2,
                    },
                    60 * 60 * 1000
                )
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
            })

            it.each([
                ['no rate limit is configured', (): void => void (invocation.hogFunction.metadata = {})],
                [
                    'the configured value is malformed',
                    (): void =>
                        void (invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 'lots' } }),
                ],
            ])('does not consult the bucket when %s', async (_name, setup) => {
                setup()

                const result = await limitedService.executeSendEmail(invocation)

                expect(claimOrReserve).not.toHaveBeenCalled()
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
            })

            it('skips the limit for test sends', async () => {
                claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: 5000 })

                const result = await limitedService.executeSendEmail(invocation, true)

                expect(claimOrReserve).not.toHaveBeenCalled()
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
            })
        })

        // A workflow over its sending limit must not crowd out anyone else: every denied
        // send parks on its own future slot instead of retrying every second, and a
        // workflow without a limit keeps sending right past the parked backlog.
        describe('a denied backlog cannot crowd out other sends', () => {
            it('spreads denied sends over distinct future slots and leaves unlimited workflows untouched', async () => {
                const redis = createRedisV2PoolFromConfig({
                    connection: hub.CDP_REDIS_HOST
                        ? {
                              url: hub.CDP_REDIS_HOST,
                              options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                          }
                        : { url: hub.REDIS_URL },
                    poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                    poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
                })
                const realLimitedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                    },
                    hub.integrationManager,
                    new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    new RateLimiterService(redis, { name: 'workflow-email-backlog-test' })
                )
                const realSendSpy = jest.spyOn(realLimitedService.sesV2Client!, 'send') as any
                realSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                // 6/minute: refill 0.1 tokens/s, burst capacity 1. Slow enough that the test's
                // own wall-clock time cannot refill a token between the denials below.
                invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 6, period: 'minute' } }

                const first = await realLimitedService.executeSendEmail(invocation)
                expect(first.finished).toBe(true)

                const parkedAt: number[] = []
                for (let i = 0; i < 4; i++) {
                    const denied = await realLimitedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }

                // Each denial must hold its own slot, one token interval (10s) apart. If the
                // parks all landed in the same window, the gaps between them would be near
                // zero or negative and the backlog would wake as one herd.
                for (let i = 1; i < parkedAt.length; i++) {
                    const gapMs = parkedAt[i] - parkedAt[i - 1]
                    expect(gapMs).toBeGreaterThan(9_000)
                    expect(gapMs).toBeLessThan(11_000)
                }

                // A workflow without a limit on the same team sends immediately, regardless of
                // the backlog next to it.
                const other = createExampleInvocation({ team_id: team.id, id: 'function-b' })
                other.id = 'invocation-b'
                other.state.vmState = { stack: [] } as any
                other.queueParameters = createEmailParams({ from: { integrationId: 1 } })
                const otherResult = await realLimitedService.executeSendEmail(other)

                expect(otherResult.finished).toBe(true)
                expect(realSendSpy).toHaveBeenCalledTimes(2)
            })
        })

        describe('team sending cap (enforce mode)', () => {
            let claimAllOrNothingPair: jest.Mock
            let cappedService: EmailService
            let cappedSendSpy: jest.SpyInstance

            beforeEach(() => {
                claimAllOrNothingPair = jest.fn()
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                jest.spyOn(configService, 'getEmailSendingTier').mockResolvedValue(0)
                cappedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                        teamEmailCapMode: 'enforce',
                        teamEmailTierHourlyCaps: [100],
                        teamEmailTierDailyCaps: [200],
                    },
                    hub.integrationManager,
                    configService,
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    null,
                    { claimAllOrNothingPair } as unknown as RateLimiterService
                )
                cappedSendSpy = jest.spyOn(cappedService.sesV2Client!, 'send') as any
                cappedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            })

            afterEach(() => {
                jest.restoreAllMocks()
            })

            it.each([
                // A reserved slot is exclusive and is parked on exactly; spreading it would
                // collide it with the slot in front.
                ['parks exactly on a reserved slot', 30 * 60 * 1000, true, 30 * 60 * 1000, 30 * 60 * 1000],
                // Past the horizon nothing is reserved: every overflow caller gets the same
                // wake back and spreads itself 1x-2x across the horizon.
                [
                    'spreads an overflow wake across the horizon',
                    60 * 60 * 1000,
                    false,
                    60 * 60 * 1000,
                    2 * 60 * 60 * 1000,
                ],
            ])('%s', async (_name, retryAfterMs, reserved, minMs, maxMs) => {
                claimAllOrNothingPair.mockResolvedValue({ granted: false, deniedIndex: 1, retryAfterMs, reserved })

                const before = Date.now()
                const result = await cappedService.executeSendEmail(invocation)

                expect(cappedSendSpy).not.toHaveBeenCalled()
                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                // The reschedule must carry the email payload forward, same as the workflow limit.
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + minMs)
                expect(scheduledMs).toBeLessThan(before + maxMs + 5000)
            })

            it('retries on the token bucket cadence when the limiter reports no horizon', async () => {
                // A Valkey fault denies with no horizon. Parking on the daily cap's pacing
                // interval would hold the email long after the limiter recovered.
                jest.spyOn(Math, 'random').mockReturnValue(0)
                claimAllOrNothingPair.mockResolvedValue({
                    granted: false,
                    deniedIndex: null,
                    retryAfterMs: null,
                    reserved: false,
                })

                const before = Date.now()
                const result = await cappedService.executeSendEmail(invocation)

                expect(cappedSendSpy).not.toHaveBeenCalled()
                expect(result.finished).toBe(false)
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + 5 * 60 * 1000)
                expect(scheduledMs).toBeLessThan(before + 5 * 60 * 1000 + 5000)
            })

            it('sends when the claim is granted', async () => {
                claimAllOrNothingPair.mockResolvedValue({
                    granted: true,
                    deniedIndex: null,
                    retryAfterMs: null,
                    reserved: false,
                })

                const result = await cappedService.executeSendEmail(invocation)

                // The reservation horizon must reach the limiter, or denials fall back to
                // shared-horizon wakes and a denied backlog re-herds.
                expect(claimAllOrNothingPair).toHaveBeenCalledWith(
                    expect.anything(),
                    expect.any(Number),
                    60 * 60 * 1000
                )
                expect(result.finished).toBe(true)
                expect(cappedSendSpy).toHaveBeenCalled()
            })

            // A team over its tier cap must not slow anyone else down: its denied sends get
            // their own future slots instead of all waking together, and another team's send
            // goes straight out. Runs against the real limiter.
            it('spreads a capped team over distinct slots while another team keeps sending', async () => {
                const hourlyCap = 360
                const dailyCap = 8640
                const redis = createRedisV2PoolFromConfig({
                    connection: hub.CDP_REDIS_HOST
                        ? {
                              url: hub.CDP_REDIS_HOST,
                              options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                          }
                        : { url: hub.REDIS_URL },
                    poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                    poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
                })
                const limiter = new RateLimiterService(redis, { name: 'team-email-cap-test' })
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                jest.spyOn(configService, 'getEmailSendingTier').mockResolvedValue(0)
                const enforcedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                        teamEmailCapMode: 'enforce',
                        teamEmailTierHourlyCaps: [hourlyCap],
                        teamEmailTierDailyCaps: [dailyCap],
                    },
                    hub.integrationManager,
                    configService,
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    null,
                    limiter
                )
                const enforcedSendSpy = jest.spyOn(enforcedService.sesV2Client!, 'send') as any
                enforcedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                // Drain the capped team's hourly bucket so every send below is a denial. The
                // 0.1 tokens/s refill makes the slot spacing 10s, far above test wall-clock.
                const buckets = teamEmailCapBuckets(team.id, hourlyCap, dailyCap)
                await limiter.claimUpTo({
                    key: buckets[0].key,
                    requested: hourlyCap,
                    capacity: buckets[0].capacity,
                    refillPerSecond: buckets[0].refillPerSecond,
                })

                const parkedAt: number[] = []
                for (let i = 0; i < 4; i++) {
                    const denied = await enforcedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }
                // Distinct slots one token interval apart, not a herd at the shared horizon.
                for (let i = 1; i < parkedAt.length; i++) {
                    const gapMs = parkedAt[i] - parkedAt[i - 1]
                    expect(gapMs).toBeGreaterThan(9_000)
                    expect(gapMs).toBeLessThan(11_000)
                }

                // A second team's buckets are cold, so its send goes straight out. Tier caps
                // isolate per team; the capped team's backlog must not reach anyone else.
                const otherTeam = (await createTestTeamFixture(hub.postgres)).team
                await insertIntegration(hub.postgres, otherTeam.id, {
                    id: otherTeam.id + 1,
                    kind: 'email',
                    config: {
                        email: 'test@posthog.com',
                        name: 'Test User',
                        domain: 'posthog.com',
                        verified: true,
                        provider: 'ses',
                    },
                })
                const other = createExampleInvocation({ team_id: otherTeam.id, id: 'function-other-team' })
                other.id = 'invocation-other-team'
                other.state.vmState = { stack: [] } as any
                other.queueParameters = createEmailParams()
                other.queueParameters.from = { integrationId: otherTeam.id + 1 }
                const otherResult = await enforcedService.executeSendEmail(other)

                expect(otherResult.finished).toBe(true)
                expect(enforcedSendSpy).toHaveBeenCalledTimes(1)
            })
        })
    })
    describe('native email sending with maildev', () => {
        let invocation: CyclotronJobInvocationHogFunction
        const mailDevAPI = new MailDevAPI()
        beforeEach(async () => {
            const actualFetch = jest.requireActual('~/common/utils/request').fetch as jest.Mock
            mockFetch.mockImplementation((...args: any[]): Promise<any> => {
                return actualFetch(...args) as any
            })
            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog.com',
                    name: 'Test User',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'maildev',
                },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = {
                stack: [],
            } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1 } })
            await mailDevAPI.clearEmails()
        })
        it('should send an email', async () => {
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            await waitForExpect(async () => expect(mailDevAPI.getEmails()).resolves.toHaveLength(1))
            const emails = await mailDevAPI.getEmails()
            expect(emails).toHaveLength(1)
            expect(emails[0]).toMatchObject({
                from: [{ address: 'test@posthog.com', name: 'Test User' }],
                html: 'Test HTML',
                subject: 'Test Subject',
                text: 'Test Text',
                to: [{ address: 'test@example.com', name: 'Test User' }],
            })
        })
        it('should include tracking code in the email with distinct_id', async () => {
            invocation.queueParameters = createEmailParams({
                html: '<body>Hi! <a href="https://example.com">Click me</a></body>',
            })
            await service.executeSendEmail(invocation)
            await waitForExpect(async () => expect(mailDevAPI.getEmails()).resolves.toHaveLength(1))
            const emails = await mailDevAPI.getEmails()
            expect(emails).toHaveLength(1)
            // ph_id may be unsigned (base64url only) or signed (base64url + `.` + signature) depending on
            // ENCRYPTION_SALT_KEYS. Match the structure, not the exact value.
            expect(emails[0].html).toMatch(
                /^<body>Hi! <a href="http:\/\/localhost:8010\/public\/m\/redirect\?ph_id=[A-Za-z0-9._-]+&target=https%3A%2F%2Fexample\.com">Click me<\/a><img src="http:\/\/localhost:8010\/public\/m\/pixel\?ph_id=[A-Za-z0-9._-]+" style="display: none;" \/><\/body>$/
            )
        })
    })
    describe('native email sending with ses', () => {
        let invocation: CyclotronJobInvocationHogFunction
        let sendEmailSpy: jest.SpyInstance
        beforeEach(async () => {
            const actualFetch = jest.requireActual('~/common/utils/request').fetch as jest.Mock
            mockFetch.mockImplementation((...args: any[]): Promise<any> => {
                return actualFetch(...args) as any
            })
            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog-test.com',
                    name: 'Test User',
                    domain: 'posthog-test.com',
                    verified: true,
                    provider: 'ses',
                },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = {
                stack: [],
            } as any
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            sendEmailSpy = jest.spyOn(service.sesV2Client!, 'send')
        })

        it('should error if not verified', async () => {
            sendEmailSpy.mockRejectedValue(new Error('Email address not verified "Test User" <test@posthog-test.com>'))
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toEqual(
                'Failed to send email via SES: Email address not verified "Test User" <test@posthog-test.com>'
            )
        })

        it('should send an email if verified', async () => {
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(sendEmailSpy).toHaveBeenCalledTimes(1)
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            // The SES tag carries the short unsigned code (no dot); the signed code (with distinct_id)
            // rides in the header.
            expect(sentCommand.input).toMatchObject({
                ConfigurationSetName: 'posthog-messaging',
                Content: {
                    Simple: {
                        Body: {
                            Html: { Charset: 'UTF-8', Data: 'Test HTML' },
                            Text: { Charset: 'UTF-8', Data: 'Test Text' },
                        },
                        Subject: { Charset: 'UTF-8', Data: 'Test Subject' },
                    },
                },
                Destination: { ToAddresses: ['"Test User" <test@example.com>'] },
                EmailTags: [{ Name: 'ph_id', Value: expect.stringMatching(/^[A-Za-z0-9_-]+$/) }],
                FeedbackForwardingEmailAddress: 'test@posthog-test.com',
                FromEmailAddress: '"Test User" <test@posthog-test.com>',
            })
        })

        it('records a send-time metric for normal sends but not for test sends', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

            const normal = await service.executeSendEmail(invocation)
            expect(normal.metrics.map((m) => m.metric_name)).toContain('email_sent')

            const testSend = await service.executeSendEmail(invocation, true)
            expect(testSend.metrics).toEqual([])
        })

        describe('suppression enforcement at send time', () => {
            // Guards the "email hog function destination bypasses shouldSkipAction, so suppression
            // isn't enforced on that path" gap. executeSendEmail is the single choke point every
            // outbound send goes through — the suppression check has to live here so it can't be
            // skipped just by choosing a different upstream code path.
            it('does not call SES when the recipient is on the suppression list', async () => {
                const isSuppressedSpy = jest
                    .spyOn(service['emailSuppressionService'], 'isSuppressed')
                    .mockResolvedValue(true)
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(isSuppressedSpy).toHaveBeenCalled()
                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_suppressed')
                expect(result.metrics.map((m) => m.metric_name)).not.toContain('email_sent')
            })

            it('calls SES when the recipient is not suppressed', async () => {
                jest.spyOn(service['emailSuppressionService'], 'isSuppressed').mockResolvedValue(false)
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })
        })

        describe('SES tenant attribution', () => {
            it('attributes the send to the team tenant', async () => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })

            it('attributes test-panel sends too — they are real SES sends', async () => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })
        })

        describe('team suspension enforcement at send time', () => {
            // Guards both suspension switches: while a team is suspended, no send path may
            // reach SES — including editor test sends, which count against the tenant too.
            // These write a real config row so they also cover the service's SELECT; mocking
            // getEmailSendingSuspension would pass with the column missing from the query.
            const suspendTeam = async (): Promise<void> => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO workflows_teamworkflowsconfig
                        (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                         email_sending_suspended_at, email_sending_suspension_reason)
                     VALUES ($1, false, 'off', now(), 'testing suspension')
                     ON CONFLICT (team_id) DO UPDATE SET email_sending_suspended_at = now()`,
                    [team.id],
                    'test-suspend-email-sending'
                )
            }

            it('does not call SES while the team is suspended and records email_suspended', async () => {
                await suspendTeam()
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics.map((m) => m.metric_name)).toEqual(['email_suspended'])
                expect(invocation.state.vmState?.stack).toEqual([{ success: false }])
            })

            it('blocks editor test sends while suspended without recording metrics', async () => {
                await suspendTeam()
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics).toEqual([])
            })

            // A per-workflow pause holds one workflow's email while the rest of the project keeps
            // sending. Same choke point as the team switch above, so no upstream route bypasses it.
            it('does not call SES while the workflow is paused and records email_paused', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: '2026-01-01T00:00:00Z',
                    email_sending_paused_reason: 'Spam complaints reached 2% of the 400 emails sent.',
                }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics.map((m) => m.metric_name)).toEqual(['email_paused'])
                expect(invocation.state.vmState?.stack).toEqual([{ success: false }])
                expect(result.logs.map((l) => l.message).join(' ')).toContain('Spam complaints reached 2%')
                // Flags the skip so the flow-level billing gate charges nothing for a send that never sent.
                expect(result.skipped).toBe(true)
            })

            it('tells a staff-paused workflow to contact support instead of the resume button', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: '2026-01-01T00:00:00Z',
                    email_sending_paused_reason:
                        "PostHog staff paused this workflow's email to protect delivery for everyone.",
                    email_sending_paused_by: 'staff',
                }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                const messages = result.logs.map((l) => l.message).join(' ')
                expect(messages).toContain('Contact support')
                expect(messages).not.toContain('Resume it from the workflow page')
            })

            it('blocks editor test sends while the workflow is paused without recording metrics', async () => {
                invocation.hogFunction.metadata = { email_sending_paused_at: '2026-01-01T00:00:00Z' }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics).toEqual([])
            })

            it('sends once the workflow pause is cleared', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: null,
                    email_sending_paused_reason: null,
                }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })

            const setProviderTenantStatus = async (status: string): Promise<void> => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    // email_sending_suspension_reason is NOT NULL and its default is Django-side,
                    // not on the column, so a raw INSERT has to supply it.
                    `INSERT INTO workflows_teamworkflowsconfig
                        (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                         email_sending_suspension_reason, ses_tenant_sending_status)
                     VALUES ($1, false, 'off', '', $2)
                     ON CONFLICT (team_id) DO UPDATE SET ses_tenant_sending_status = $2`,
                    [team.id, status],
                    'test-set-ses-tenant-sending-status'
                )
            }

            // A paused provider tenant rejects every send, so the send path has to read the stored
            // state. Only DISABLED blocks: REINSTATED is what a tenant the provider has restored
            // reads, so treating any non-ENABLED status as paused would withhold accepted sends.
            it.each([
                ['DISABLED', 0, 'email_suspended'],
                ['REINSTATED', 1, 'email_sent'],
            ])('provider tenant status %s: %i SES calls, records %s', async (status, sesCalls, metricName) => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                await setProviderTenantStatus(status as string)

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(sesCalls as number)
                expect(result.metrics.map((m) => m.metric_name)).toContain(metricName)
            })

            // The send path caches this row for minutes, so a pause that lands after the first read
            // would keep sending — and a reinstatement would keep blocking — until the entry aged
            // out. The provider state sync announces each change to close that window.
            it('picks up a provider status change announced while the config is cached', async () => {
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                await setProviderTenantStatus('ENABLED')
                expect(await configService.getEmailSendingSuspension(team.id)).toBeNull()

                await setProviderTenantStatus('DISABLED')

                await waitForExpect(async () => {
                    // Republished every poll: subscribing is asynchronous, so the first publish can
                    // land before this subscriber is listening. Marking for refresh is idempotent.
                    await hub.pubSub.publish('reload-team-workflows-config', JSON.stringify({ teamId: team.id }))
                    expect(await configService.getEmailSendingSuspension(team.id)).toEqual('provider')
                }, 3000)
            })

            it('fails open when the suspension lookup errors', async () => {
                // The config lookup rejecting must never block a legitimate send. Rejects once:
                // the suspension check is the first config read; later reads use the real loader.
                jest.spyOn(service['teamWorkflowsConfigService'], 'get').mockRejectedValueOnce(new Error('pg down'))
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })
        })

        it('should include cc addresses in SES destination', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                cc: 'cc1@example.com, cc2@example.com',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.CcAddresses).toEqual(['cc1@example.com', 'cc2@example.com'])
        })

        it('should include bcc addresses in SES destination', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                bcc: 'bcc@example.com',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.BccAddresses).toEqual(['bcc@example.com'])
        })

        it('should not include cc/bcc in SES destination when not provided', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.CcAddresses).toBeUndefined()
            expect(sentCommand.input.Destination.BccAddresses).toBeUndefined()
        })

        it('should not include cc/bcc in SES destination when empty strings', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                cc: '',
                bcc: '  ',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.CcAddresses).toBeUndefined()
            expect(sentCommand.input.Destination.BccAddresses).toBeUndefined()
        })

        it('should not include replyTo if not in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.ReplyToAddresses).toBeUndefined()
        })

        it('should include single replyTo address if in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                replyTo: 'Customer Service <reply@example.com>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.ReplyToAddresses).toEqual(['Customer Service <reply@example.com>'])
        })

        it('should split multiple comma-separated replyTo addresses', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                replyTo: 'reply1@example.com, reply2@example.com, Customer Service <reply3@example.com>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.ReplyToAddresses).toEqual([
                'reply1@example.com',
                'reply2@example.com',
                'Customer Service <reply3@example.com>',
            ])
        })

        it('should send plaintext-only email when html is empty', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html: '',
                text: 'Hello, this is a plain text email.',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Content.Simple.Body.Text).toEqual({
                Data: 'Hello, this is a plain text email.',
                Charset: 'UTF-8',
            })
            expect(sentCommand.input.Content.Simple.Body.Html).toBeUndefined()
        })

        it('should not include preheader span if not in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html: '<tbody>Test email content</tbody>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const htmlData = sentCommand.input.Content.Simple.Body.Html.Data
            expect(htmlData).not.toContain('<tbody><span')
        })

        it('should include preheader at top of HTML if in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html: '<tbody>Test email content</tbody>',
                preheader: 'This is a preview text',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const htmlData = sentCommand.input.Content.Simple.Body.Html.Data
            expect(htmlData).toMatch(/<tbody><span style=".*">This is a preview text<\/span>/)
        })

        it('should include unsubscribe headers for non-transactional emails', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'marketing' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const headers = sentCommand.input.Content.Simple.Headers
            expect(headers).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ Name: 'List-Unsubscribe' }),
                    expect.objectContaining({ Name: 'List-Unsubscribe-Post' }),
                ])
            )
        })

        it('should not include unsubscribe headers for transactional emails (but tracking-code header is still set)', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const headerNames = (sentCommand.input.Content.Simple.Headers ?? []).map((h: { Name: string }) => h.Name)
            expect(headerNames).not.toContain('List-Unsubscribe')
            expect(headerNames).not.toContain('List-Unsubscribe-Post')
            expect(headerNames).toContain('X-PostHog-Tracking-Code')
        })

        it('attaches the X-PostHog-Tracking-Code header carrying the full signed code', async () => {
            // The header is the authoritative tracking-code carrier (the EmailTag is the
            // bounded backwards-compat fallback). It rides on every outbound message,
            // regardless of transactional vs. marketing category.
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const trackingHeader = sentCommand.input.Content.Simple.Headers.find(
                (h: { Name: string }) => h.Name === 'X-PostHog-Tracking-Code'
            )
            expect(trackingHeader).toBeDefined()
            expect(typeof trackingHeader.Value).toBe('string')
            expect(trackingHeader.Value.length).toBeGreaterThan(0)
            // The SES EmailTag carries a *different* (shorter, unsigned) code so it stays under the
            // 256-char tag-value limit even when distinct_id is long.
            expect(sentCommand.input.EmailTags[0].Value).not.toEqual(trackingHeader.Value)
        })

        describe('per-send tracking gate (tracking_enabled)', () => {
            // Would be tracked if the gate regressed: has an anchor to rewrite and a </body> to pixel.
            const trackableHtml = '<body>Hi! <a href="https://example.com">Click me</a></body>'

            beforeEach(() => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.queueParameters = createEmailParams({ from: { integrationId: 1 }, html: trackableHtml })
                invocation.hogFunction.metadata = { tracking_enabled: false }
            })

            it('skips pixel and link rewriting and uses the untracked configuration set when tracking is off', async () => {
                service['sesConfig'].sesUntrackedConfigurationSet = 'posthog-messaging-untracked'
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.ConfigurationSetName).toEqual('posthog-messaging-untracked')
                expect(sentCommand.input.Content.Simple.Body.Html.Data).toEqual(trackableHtml)
                // Delivery/bounce attribution must survive tracking-off: the untracked configuration
                // set still emits delivery events, and the webhook needs this header to attribute them.
                const headerNames = sentCommand.input.Content.Simple.Headers.map((h: { Name: string }) => h.Name)
                expect(headerNames).toContain('X-PostHog-Tracking-Code')
            })

            it('falls back to the tracked configuration set when no untracked set is configured, still untracked HTML', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.ConfigurationSetName).toEqual('posthog-messaging')
                expect(sentCommand.input.Content.Simple.Body.Html.Data).toEqual(trackableHtml)
            })

            it('records an email_untracked app metric for untracked sends but not for test sends', async () => {
                const normal = await service.executeSendEmail(invocation)
                expect(normal.metrics.map((m) => m.metric_name)).toEqual(
                    expect.arrayContaining(['email_sent', 'email_untracked'])
                )

                const testSend = await service.executeSendEmail(invocation, true)
                expect(testSend.metrics).toEqual([])
            })

            it('marks the captured send event as untracked so customer-built engagement rates can exclude it', async () => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'shouldCaptureEngagementEvents'
                ).mockResolvedValue(true)
                const result = await service.executeSendEmail(invocation)
                expect(result.capturedPostHogEvents[0].properties).toMatchObject({
                    $email_tracking_enabled: false,
                })
            })
        })

        describe('recipient tracking consent', () => {
            const trackableHtml = '<body>Hi! <a href="https://example.com">Click me</a></body>'

            const setConsentState = (
                mode: 'off' | 'opt_out' | 'opt_in',
                storedConsent: 'OPTED_IN' | 'OPTED_OUT' | null
            ): void => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockResolvedValue(mode)
                jest.spyOn((service as any).recipientsManager, 'get').mockResolvedValue(
                    storedConsent
                        ? {
                              id: 'pref-1',
                              team_id: team.id,
                              identifier: 'test@example.com',
                              preferences: { $email_tracking: storedConsent },
                              created_at: '',
                              updated_at: '',
                          }
                        : null
                )
            }

            beforeEach(() => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.queueParameters = createEmailParams({ from: { integrationId: 1 }, html: trackableHtml })
                invocation.hogFunction.metadata = { message_category_type: 'marketing' }
            })

            it.each([
                ['off mode ignores consent entirely', 'off', null, true],
                ['opt_out mode tracks recipients with no stored preference', 'opt_out', null, true],
                ['opt_out mode does not track recipients who opted out', 'opt_out', 'OPTED_OUT', false],
                ['opt_in mode does not track recipients with no stored preference', 'opt_in', null, false],
                ['opt_in mode tracks recipients who opted in', 'opt_in', 'OPTED_IN', true],
            ] as [string, 'off' | 'opt_out' | 'opt_in', 'OPTED_IN' | 'OPTED_OUT' | null, boolean][])(
                '%s',
                async (_name, mode, storedConsent, expectTracked) => {
                    setConsentState(mode, storedConsent)
                    const result = await service.executeSendEmail(invocation)
                    expect(result.error).toBeUndefined()
                    const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html
                        .Data
                    if (expectTracked) {
                        // SES sends tag each anchor and let SES report the click, instead of
                        // rewriting the href to a redirect URL. The open pixel is unchanged.
                        expect(sentHtml).toContain('ses:tags="phl:')
                        expect(sentHtml).toContain('ph_id=')
                    } else {
                        expect(sentHtml).toEqual(trackableHtml)
                    }
                }
            )

            it('transactional emails are exempt from consent enforcement', async () => {
                invocation.hogFunction.metadata = { message_category_type: 'transactional' }
                setConsentState('opt_in', null)
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toContain('ses:tags="phl:')
                expect(sentHtml).toContain('ph_id=')
            })

            it('the step-level toggle wins over consent: tracking_enabled false is untracked even for opted-in recipients', async () => {
                invocation.hogFunction.metadata = { message_category_type: 'marketing', tracking_enabled: false }
                setConsentState('opt_in', 'OPTED_IN')
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('sends untracked when the consent lookup fails (fail closed)', async () => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockResolvedValue('opt_out')
                jest.spyOn((service as any).recipientsManager, 'get').mockRejectedValue(new Error('db down'))
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('sends untracked when the consent-mode lookup fails (fail closed)', async () => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockRejectedValue(new Error('db down'))
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('honors a cc recipient tracking opt-out for the whole send', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                    html: trackableHtml,
                    cc: 'cc@example.com',
                })
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockResolvedValue('opt_out')
                jest.spyOn((service as any).recipientsManager, 'get').mockImplementation(
                    (options: unknown): Promise<any> => {
                        const { identifier } = options as { identifier: string }
                        return Promise.resolve(
                            identifier === 'cc@example.com'
                                ? {
                                      id: 'pref-1',
                                      team_id: team.id,
                                      identifier,
                                      preferences: { $email_tracking: 'OPTED_OUT' },
                                      created_at: '',
                                      updated_at: '',
                                  }
                                : null
                        )
                    }
                )
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })
        })

        it('should report a missing message id', async () => {
            sendEmailSpy.mockResolvedValue({})
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toMatchInlineSnapshot(`"Failed to send email via SES: No messageId returned from SES"`)
        })

        it('should capture a $workflows_email_sent PostHog event on success', async () => {
            // Engagement capture is team-opt-in; enable it for this team so the captured event is emitted.
            jest.spyOn((service as any).teamWorkflowsConfigService, 'shouldCaptureEngagementEvents').mockResolvedValue(
                true
            )
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toHaveLength(1)
            expect(result.capturedPostHogEvents[0]).toMatchObject({
                team_id: team.id,
                distinct_id: 'distinct_id',
                event: '$workflows_email_sent',
                properties: {
                    $workflow_id: invocation.functionId,
                    $workflow_action_id: invocation.state.actionId,
                    $email_to: 'test@example.com',
                    $email_subject: 'Test Subject',
                    $email_tracking_enabled: true,
                },
            })
        })

        it('does not capture a PostHog event when engagement capture is disabled for the team', async () => {
            // Default config has capture_workflows_engagement_events=false, so even on success no event is queued.
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toHaveLength(0)
        })

        it('should capture a $workflows_email_failed PostHog event on failure', async () => {
            jest.spyOn((service as any).teamWorkflowsConfigService, 'shouldCaptureEngagementEvents').mockResolvedValue(
                true
            )
            sendEmailSpy.mockRejectedValue(new Error('SES error'))
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeDefined()
            expect(result.capturedPostHogEvents).toHaveLength(1)
            expect(result.capturedPostHogEvents[0]).toMatchObject({
                event: '$workflows_email_failed',
                distinct_id: 'distinct_id',
            })
        })
    })
})
