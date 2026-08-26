import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { MessageRejected, SendingPausedException, TooManyRequestsException } from '@aws-sdk/client-sesv2'

import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { waitForExpect } from '~/tests/helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from './email-suppression.service'
import { EmailService, parseAddressList, sanitizeEmailSubject } from './email.service'
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

const createEmailParams = (
    params: Partial<CyclotronInvocationQueueParametersEmailType> = {}
): CyclotronInvocationQueueParametersEmailType => {
    return {
        type: 'email',
        to: { email: 'test@example.com', name: 'Test User' },
        from: { integrationId: 1 },
        subject: 'Test Subject',
        text: 'Test Text',
        html: 'Test HTML',
        ...params,
    }
}
describe('EmailService', () => {
    let service: EmailService
    let hub: Hub
    let team: Team
    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({})
        team = await getFirstTeam(hub.postgres)
        service = new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
                sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                sesTenantAttributionEnabled: hub.EMAIL_SES_TENANT_ATTRIBUTION_ENABLED,
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres),
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
                    sesTenantAttributionEnabled: false,
                },
                hub.integrationManager,
                new TeamWorkflowsConfigService(hub.postgres),
                hub.ENCRYPTION_SALT_KEYS,
                hub.SITE_URL,
                new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                new RecipientsManagerService(hub.postgres)
            )
            expect(serviceWithoutSES.sesV2Client).toBeNull()

            await insertIntegration(hub.postgres, team.id, {
                id: 1,
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
                id: 1,
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
                    id: 2,
                    kind: 'email',
                    config: {
                        email: 'test@other-domain.com',
                        name: 'Test User',
                        domain: 'other-domain.com',
                        verified: false,
                    },
                })
                await insertIntegration(hub.postgres, team.id, {
                    id: 3,
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
                    id: 4,
                    kind: 'email',
                    config: {
                        email: 'second@posthog.com',
                        name: 'Second Sender',
                        domain: 'posthog.com',
                        verified: true,
                        provider: 'ses',
                    },
                })
                invocation.id = 'invocation-0'
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
            let claimUpTo: jest.Mock
            let limitedService: EmailService
            let limitedSendSpy: jest.SpyInstance

            beforeEach(() => {
                claimUpTo = jest.fn().mockResolvedValue(1)
                limitedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                        sesTenantAttributionEnabled: hub.EMAIL_SES_TENANT_ATTRIBUTION_ENABLED,
                    },
                    hub.integrationManager,
                    new TeamWorkflowsConfigService(hub.postgres),
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    { claimUpTo } as unknown as RateLimiterService
                )
                limitedSendSpy = jest.spyOn(limitedService.sesV2Client!, 'send') as any
                limitedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.hogFunction.metadata = {
                    email_sending_rate_limit: { count: 120, period: 'minute' },
                }
            })

            it('reschedules without sending when the bucket denies a token', async () => {
                claimUpTo.mockResolvedValue(0)

                const before = Date.now()
                const result = await limitedService.executeSendEmail(invocation)

                expect(limitedSendSpy).not.toHaveBeenCalled()
                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                // The reschedule must carry the email payload forward: without queueParameters the
                // retry has nothing to send and the throttled email is dropped rather than delayed.
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                // 120/minute refills a token every 500ms, so the clamped jittered wake lands in [1s, 2s].
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + 1000)
                expect(scheduledMs).toBeLessThan(before + 3000)
                // No business metric on a pacing delay — the eventual send produces email_sent.
                expect(result.metrics ?? []).toEqual([])
            })

            it('claims one token scoped to the workflow and sends when granted', async () => {
                const result = await limitedService.executeSendEmail(invocation)

                expect(claimUpTo).toHaveBeenCalledWith({
                    key: `@posthog/workflow-email-rate/${team.id}/function-1`,
                    requested: 1,
                    // Burst capacity is ~1s of budget (not the count), so the first period can't
                    // send ~2x the limit and an idle-expired bucket can't re-burst.
                    capacity: 2,
                    refillPerSecond: 2,
                })
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

                expect(claimUpTo).not.toHaveBeenCalled()
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
            })

            it('skips the limit for test sends', async () => {
                claimUpTo.mockResolvedValue(0)

                const result = await limitedService.executeSendEmail(invocation, true)

                expect(claimUpTo).not.toHaveBeenCalled()
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
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
                id: 1,
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
                id: 1,
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
            it('attributes the send to the team tenant when enabled', async () => {
                service['sesConfig'].sesTenantAttributionEnabled = true
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })

            it('omits TenantName by default (flag off)', async () => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.TenantName).toBeUndefined()
            })

            it('attributes test-panel sends too — they are real SES sends', async () => {
                service['sesConfig'].sesTenantAttributionEnabled = true
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })
        })

        describe('team suspension enforcement at send time', () => {
            // Guards the reputation kill switch: while a team is suspended, no send path may
            // reach SES — including editor test sends, which count against the tenant too.
            // The first two write a real row so they also cover the service's SELECT; mocking
            // isEmailSendingSuspended would pass with the column missing from the query.
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
