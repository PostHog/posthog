import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { MessageRejected, SendingPausedException, TooManyRequestsException } from '@aws-sdk/client-sesv2'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailSchema } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { EmailInvocationFixture, EmailServiceFixture, createMessageAssetsService } from '~/tests/helpers/email'
import { waitForExpect } from '~/tests/helpers/expectations'
import { SesEmailRequest } from '~/tests/helpers/ses'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { selectEmailSenderIntegrationId } from './email-sender-selection'
import { EmailService, parseAddressList, sanitizeEmailSubject, teamEmailCapBuckets } from './email.service'
import { MailDevAPI } from './helpers/maildev'

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

describe('EmailService', () => {
    let service: EmailService
    let hub: Hub
    let team: Team
    let services: EmailServiceFixture
    let emails: EmailInvocationFixture
    let createEmailParams: EmailInvocationFixture['params']
    let getIntegrationId: EmailInvocationFixture['integrationId']
    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team
        services = new EmailServiceFixture(hub)
        emails = new EmailInvocationFixture(team.id)
        createEmailParams = emails.params
        getIntegrationId = emails.integrationId
        service = services.create()
        mockFetch.mockClear()
    })
    afterEach(async () => {
        await services.close()
        await closeHub(hub)
    })
    describe('when SES is not configured', () => {
        it('should not crash on construction and should fail explicitly on send', async () => {
            const serviceWithoutSES = services.create({
                sesConfig: {
                    sesAccessKeyId: '',
                    sesSecretAccessKey: '',
                    sesRegion: '',
                    sesEndpoint: '',
                    sesTrackedConfigurationSet: 'posthog-messaging',
                    sesUntrackedConfigurationSet: '',
                },
            })
            expect(serviceWithoutSES.sesV2Client).toBeNull()

            await insertIntegration(hub.postgres, team.id, emails.sender())
            const invocation = emails.invocation()

            const result = await serviceWithoutSES.executeSendEmail(invocation)
            expect(result.error).toBe('SES is not configured - set SES_REGION and AWS credentials')
        })
    })

    describe('executeSendEmail', () => {
        let invocation: CyclotronJobInvocationHogFunction
        let sendEmailSpy: jest.SpyInstance
        beforeEach(async () => {
            await insertIntegration(hub.postgres, team.id, emails.sender())
            invocation = emails.invocation()
            sendEmailSpy = jest.spyOn(service.sesV2Client!, 'send')
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
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalled()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
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
                const sentCommand = new SesEmailRequest(sendEmailSpy)
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
                const sentCommand = new SesEmailRequest(sendEmailSpy)
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
                expect(result.error).toBeUndefined()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
                expect(sentCommand.input.FromEmailAddress).toBe('"Test User" <test@posthog.com>')
                expect(result.logs.some((log) => log.level === 'warn' && log.message.includes(email))).toBe(true)
            })
        })
        describe('email sending', () => {
            it('should send an email', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalled()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
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
                expect(scheduledMs).toBeGreaterThanOrEqual(before + 400)
                expect(scheduledMs).toBeLessThan(before + 2000)
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                expect(result.metrics ?? []).toEqual([])
            })

            it('keeps the send priority class across a throttle reschedule', async () => {
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
                limitedService = services.create({
                    workflowEmailRateLimiter: { claimOrReserve } as unknown as RateLimiterService,
                })
                limitedSendSpy = jest.spyOn(limitedService.sesV2Client!, 'send')
                limitedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.hogFunction.metadata = {
                    email_sending_rate_limit: { count: 120, period: 'minute' },
                }
            })

            it.each([
                ['exactly at the reserved slot', 5000, true, 5000, 5000],
                ['exactly at a sub-second reserved slot', 500, true, 500, 500],
                [
                    'with spread when re-contending at the horizon',
                    60 * 60 * 1000,
                    false,
                    60 * 60 * 1000,
                    2 * 60 * 60 * 1000,
                ],
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
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + minDelayMs)
                expect(scheduledMs).toBeLessThanOrEqual(after + maxDelayMs)
                expect(result.metrics ?? []).toEqual([])
            })

            it('parks consecutive denials on their exact reserved slots', async () => {
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
                claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: 60 * 60 * 1000, reserved: false })

                const parkedAt: number[] = []
                for (let i = 0; i < 20; i++) {
                    const denied = await limitedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }
                const spreadMs = Math.max(...parkedAt) - Math.min(...parkedAt)
                expect(spreadMs).toBeGreaterThan(10 * 60 * 1000)
            })

            it('claims one token scoped to the workflow and sends when granted', async () => {
                const result = await limitedService.executeSendEmail(invocation)

                expect(claimOrReserve).toHaveBeenCalledWith(
                    {
                        key: `@posthog/workflow-email-rate/${team.id}/function-1`,
                        requested: 1,
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
        describe('a denied backlog cannot crowd out other sends', () => {
            it('spreads denied sends over distinct future slots and leaves unlimited workflows untouched', async () => {
                const redis = services.createRateLimiterRedis()
                const realLimitedService = services.create({
                    workflowEmailRateLimiter: new RateLimiterService(redis, { name: 'workflow-email-backlog-test' }),
                })
                const realSendSpy: jest.SpyInstance = jest.spyOn(realLimitedService.sesV2Client!, 'send')
                realSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 6, period: 'minute' } }

                const first = await realLimitedService.executeSendEmail(invocation)
                expect(first.finished).toBe(true)

                const parkedAt: number[] = []
                for (let i = 0; i < 4; i++) {
                    const denied = await realLimitedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }
                for (let i = 1; i < parkedAt.length; i++) {
                    const gapMs = parkedAt[i] - parkedAt[i - 1]
                    expect(gapMs).toBeGreaterThan(9_000)
                    expect(gapMs).toBeLessThan(11_000)
                }
                const other = emails.invocation({ team_id: team.id, id: 'function-b' }, 'invocation-b')
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
                cappedService = services.create({
                    sesConfig: {
                        teamEmailCapMode: 'enforce',
                        teamEmailTierHourlyCaps: [100],
                        teamEmailTierDailyCaps: [200],
                    },
                    teamWorkflowsConfigService: configService,
                    teamEmailRateLimiter: { claimAllOrNothingPair } as unknown as RateLimiterService,
                })
                cappedSendSpy = jest.spyOn(cappedService.sesV2Client!, 'send')
                cappedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            })

            afterEach(() => {
                jest.restoreAllMocks()
            })

            it.each([
                ['parks exactly on a reserved slot', 30 * 60 * 1000, true, 30 * 60 * 1000, 30 * 60 * 1000],
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
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + minMs)
                expect(scheduledMs).toBeLessThan(before + maxMs + 5000)
                expect(result.logs.map((log) => log.message).join(' ')).toContain('reached its email sending limit of')
            })

            it('retries on the token bucket cadence when the limiter reports no horizon', async () => {
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
                const messages = result.logs.map((log) => log.message).join(' ')
                expect(messages).not.toContain('reached its email sending limit')
                expect(messages).toContain("Could not check this project's email sending limit")
            })

            it('sends when the claim is granted', async () => {
                claimAllOrNothingPair.mockResolvedValue({
                    granted: true,
                    deniedIndex: null,
                    retryAfterMs: null,
                    reserved: false,
                })

                const result = await cappedService.executeSendEmail(invocation)
                expect(claimAllOrNothingPair).toHaveBeenCalledWith(
                    expect.anything(),
                    expect.any(Number),
                    60 * 60 * 1000
                )
                expect(result.finished).toBe(true)
                expect(cappedSendSpy).toHaveBeenCalled()
            })
            it('spreads a capped team over distinct slots while another team keeps sending', async () => {
                const hourlyCap = 360
                const dailyCap = 8640
                const redis = services.createRateLimiterRedis()
                const limiter = new RateLimiterService(redis, { name: 'team-email-cap-test' })
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                jest.spyOn(configService, 'getEmailSendingTier').mockResolvedValue(0)
                const enforcedService = services.create({
                    sesConfig: {
                        teamEmailCapMode: 'enforce',
                        teamEmailTierHourlyCaps: [hourlyCap],
                        teamEmailTierDailyCaps: [dailyCap],
                    },
                    teamWorkflowsConfigService: configService,
                    teamEmailRateLimiter: limiter,
                })
                const enforcedSendSpy: jest.SpyInstance = jest.spyOn(enforcedService.sesV2Client!, 'send')
                enforcedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
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
                for (let i = 1; i < parkedAt.length; i++) {
                    const gapMs = parkedAt[i] - parkedAt[i - 1]
                    expect(gapMs).toBeGreaterThan(9_000)
                    expect(gapMs).toBeLessThan(11_000)
                }
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
                const other = emails.invocation(
                    { team_id: otherTeam.id, id: 'function-other-team' },
                    'invocation-other-team'
                )
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
            const actualFetch =
                jest.requireActual<typeof import('~/common/utils/request')>('~/common/utils/request').fetch
            mockFetch.mockImplementation(actualFetch)
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
            invocation = emails.invocation()
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
            expect(emails[0].html).toMatch(
                /^<body>Hi! <a href="http:\/\/localhost:8010\/public\/m\/redirect\?ph_id=[A-Za-z0-9._-]+&target=https%3A%2F%2Fexample\.com">Click me<\/a><img src="http:\/\/localhost:8010\/public\/m\/pixel\?ph_id=[A-Za-z0-9._-]+" style="display: none;" \/><\/body>$/
            )
        })
    })
    describe('native email sending with ses', () => {
        let invocation: CyclotronJobInvocationHogFunction
        let sendEmailSpy: jest.SpyInstance
        beforeEach(async () => {
            const actualFetch =
                jest.requireActual<typeof import('~/common/utils/request')>('~/common/utils/request').fetch
            mockFetch.mockImplementation(actualFetch)
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
            invocation = emails.invocation()
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
            const sentCommand = new SesEmailRequest(sendEmailSpy)
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
            it('does not call SES when the recipient is on the suppression list', async () => {
                const isSuppressedSpy = jest.spyOn(services.suppression, 'isSuppressed').mockResolvedValue(true)
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(isSuppressedSpy).toHaveBeenCalled()
                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_suppressed')
                expect(result.metrics.map((m) => m.metric_name)).not.toContain('email_sent')
            })

            it('calls SES when the recipient is not suppressed', async () => {
                jest.spyOn(services.suppression, 'isSuppressed').mockResolvedValue(false)
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
                const sentCommand = new SesEmailRequest(sendEmailSpy)
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })

            it('attributes test-panel sends too — they are real SES sends', async () => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(result.error).toBeUndefined()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })
        })

        describe('team suspension enforcement at send time', () => {
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
                    `INSERT INTO workflows_teamworkflowsconfig
                        (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                         email_sending_suspension_reason, ses_tenant_sending_status)
                     VALUES ($1, false, 'off', '', $2)
                     ON CONFLICT (team_id) DO UPDATE SET ses_tenant_sending_status = $2`,
                    [team.id, status],
                    'test-set-ses-tenant-sending-status'
                )
            }
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
            it('picks up a provider status change announced while the config is cached', async () => {
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                await setProviderTenantStatus('ENABLED')
                expect(await configService.getEmailSendingSuspension(team.id)).toBeNull()

                await setProviderTenantStatus('DISABLED')

                await waitForExpect(async () => {
                    await hub.pubSub.publish('reload-team-workflows-config', JSON.stringify({ teamId: team.id }))
                    expect(await configService.getEmailSendingSuspension(team.id)).toEqual('provider')
                }, 3000)
            })

            it('fails open when the suspension lookup errors', async () => {
                jest.spyOn(services.workflowsConfig, 'get').mockRejectedValueOnce(new Error('pg down'))
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
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            expect(sentCommand.input.Destination!.CcAddresses).toEqual(['cc1@example.com', 'cc2@example.com'])
        })

        it('should include bcc addresses in SES destination', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                bcc: 'bcc@example.com',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            expect(sentCommand.input.Destination!.BccAddresses).toEqual(['bcc@example.com'])
        })

        it('should not include cc/bcc in SES destination when not provided', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            expect(sentCommand.input.Destination!.CcAddresses).toBeUndefined()
            expect(sentCommand.input.Destination!.BccAddresses).toBeUndefined()
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
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            expect(sentCommand.input.Destination!.CcAddresses).toBeUndefined()
            expect(sentCommand.input.Destination!.BccAddresses).toBeUndefined()
        })

        it('should not include replyTo if not in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = new SesEmailRequest(sendEmailSpy)
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
            const sentCommand = new SesEmailRequest(sendEmailSpy)
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
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            expect(sentCommand.input.ReplyToAddresses).toEqual([
                'reply1@example.com',
                'reply2@example.com',
                'Customer Service <reply3@example.com>',
            ])
        })

        it.each([
            ['text only', { html: '', text: 'Hello, this is a plain text email.' }, ['Text']],
            ['html only, no text', { html: '<p>Hello</p>', text: undefined }, ['Html']],
            ['html only, empty text', { html: '<p>Hello</p>', text: '' }, ['Html']],
        ])('sends only the parts that have content: %s', async (_name, content, expectedParts) => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            invocation.queueParameters = CyclotronInvocationQueueParametersEmailSchema.parse(
                createEmailParams({ from: { integrationId: 1 }, ...content })
            )
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            expect(Object.keys(sentCommand.body!)).toEqual(expectedParts)
            if (content.text) {
                expect(sentCommand.body.Text).toEqual({ Data: content.text, Charset: 'UTF-8' })
            }
        })

        it('should not include preheader span if not in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html: '<tbody>Test email content</tbody>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            const htmlData = sentCommand.html
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
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            const htmlData = sentCommand.html
            expect(htmlData).toMatch(/<tbody><span style=".*">This is a preview text<\/span>/)
        })

        it('should include unsubscribe headers for non-transactional emails', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'marketing' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            const headers = sentCommand.headers
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
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            const headerNames = sentCommand.headers.map((h) => h.Name)
            expect(headerNames).not.toContain('List-Unsubscribe')
            expect(headerNames).not.toContain('List-Unsubscribe-Post')
            expect(headerNames).toContain('X-PostHog-Tracking-Code')
        })

        it.each(['transactional', 'marketing'])(
            'marks a %s send as auto-generated so autoresponders do not answer it',
            async (categoryType) => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.hogFunction.metadata = { message_category_type: categoryType }
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
                expect(sentCommand.headers).toEqual(
                    expect.arrayContaining([{ Name: 'Auto-Submitted', Value: 'auto-generated' }])
                )
            }
        )

        it('attaches the X-PostHog-Tracking-Code header carrying the full signed code', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = new SesEmailRequest(sendEmailSpy)
            const trackingHeader = sentCommand.headers.find((h) => h.Name === 'X-PostHog-Tracking-Code')
            expect(trackingHeader).toBeDefined()
            expect(typeof trackingHeader!.Value).toBe('string')
            expect(trackingHeader!.Value!.length).toBeGreaterThan(0)
            expect(sentCommand.input.EmailTags![0].Value).not.toEqual(trackingHeader!.Value)
        })

        describe('per-send tracking gate (tracking_enabled)', () => {
            const trackableHtml = '<body>Hi! <a href="https://example.com">Click me</a></body>'

            beforeEach(() => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.queueParameters = createEmailParams({ from: { integrationId: 1 }, html: trackableHtml })
                invocation.hogFunction.metadata = { tracking_enabled: false }
            })

            it('skips pixel and link rewriting and uses the untracked configuration set when tracking is off', async () => {
                services.sesConfig.sesUntrackedConfigurationSet = 'posthog-messaging-untracked'
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
                expect(sentCommand.input.ConfigurationSetName).toEqual('posthog-messaging-untracked')
                expect(sentCommand.html).toEqual(trackableHtml)
                const headerNames = sentCommand.headers.map((h) => h.Name)
                expect(headerNames).toContain('X-PostHog-Tracking-Code')
            })

            it.each([
                {
                    case: 'the workflow and step names',
                    utmParams: undefined,
                    query: 'utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Spring%20sale&amp;utm_content=Welcome',
                },
                {
                    case: 'rendered custom values',
                    utmParams: { utm_source: 'newsletter', utm_campaign: '{{ "pro" | upcase }}' },
                    query: 'utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign=PRO&amp;utm_content=Welcome',
                },
                {
                    case: 'a rendered value with characters HTML escapes',
                    utmParams: { utm_campaign: '{{ "Starter & Premium" }}' },
                    query: 'utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Starter%20%26%20Premium&amp;utm_content=Welcome',
                },
                {
                    case: 'the default for a value with a Liquid error',
                    utmParams: { utm_campaign: '{{ person.properties.plan' },
                    query: 'utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Spring%20sale&amp;utm_content=Welcome',
                },
            ])('tags the links with $case when the step turns UTM tags on', async ({ utmParams, query }) => {
                invocation.hogFunction.metadata = {
                    tracking_enabled: false,
                    utm_tags_enabled: true,
                    utm_params: utmParams,
                    hog_flow_name: 'Spring sale',
                    hog_flow_action_name: 'Welcome',
                }
                const messageAssets = createMessageAssetsService()
                const buildRowForEmail = jest.spyOn(messageAssets, 'buildRowForEmail').mockReturnValue(null)
                service = services.create({ messageAssetsService: messageAssets })
                sendEmailSpy = jest.spyOn(service.sesV2Client!, 'send')
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
                const taggedHtml = `<body>Hi! <a href="https://example.com?${query}">Click me</a></body>`
                expect(sentCommand.html).toEqual(taggedHtml)
                expect(buildRowForEmail).toHaveBeenCalledWith(
                    expect.anything(),
                    expect.objectContaining({ html: taggedHtml })
                )
            })

            it('falls back to the tracked configuration set when no untracked set is configured, still untracked HTML', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = new SesEmailRequest(sendEmailSpy)
                expect(sentCommand.input.ConfigurationSetName).toEqual('posthog-messaging')
                expect(sentCommand.html).toEqual(trackableHtml)
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
                jest.spyOn(services.workflowsConfig, 'shouldCaptureEngagementEvents').mockResolvedValue(true)
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
                jest.spyOn(services.workflowsConfig, 'getEmailTrackingConsentMode').mockResolvedValue(mode)
                jest.spyOn(services.recipients, 'get').mockResolvedValue(
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
                    const sentHtml = new SesEmailRequest(sendEmailSpy).html
                    if (expectTracked) {
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
                const sentHtml = new SesEmailRequest(sendEmailSpy).html
                expect(sentHtml).toContain('ses:tags="phl:')
                expect(sentHtml).toContain('ph_id=')
            })

            it('the step-level toggle wins over consent: tracking_enabled false is untracked even for opted-in recipients', async () => {
                invocation.hogFunction.metadata = { message_category_type: 'marketing', tracking_enabled: false }
                setConsentState('opt_in', 'OPTED_IN')
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = new SesEmailRequest(sendEmailSpy).html
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('sends untracked when the consent lookup fails (fail closed)', async () => {
                jest.spyOn(services.workflowsConfig, 'getEmailTrackingConsentMode').mockResolvedValue('opt_out')
                jest.spyOn(services.recipients, 'get').mockRejectedValue(new Error('db down'))
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = new SesEmailRequest(sendEmailSpy).html
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('sends untracked when the consent-mode lookup fails (fail closed)', async () => {
                jest.spyOn(services.workflowsConfig, 'getEmailTrackingConsentMode').mockRejectedValue(
                    new Error('db down')
                )
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = new SesEmailRequest(sendEmailSpy).html
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('honors a cc recipient tracking opt-out for the whole send', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                    html: trackableHtml,
                    cc: 'cc@example.com',
                })
                jest.spyOn(services.workflowsConfig, 'getEmailTrackingConsentMode').mockResolvedValue('opt_out')
                jest.spyOn(services.recipients, 'get').mockImplementation(
                    ({ identifier }): ReturnType<typeof services.recipients.get> => {
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
                const sentHtml = new SesEmailRequest(sendEmailSpy).html
                expect(sentHtml).toEqual(trackableHtml)
            })
        })

        it('should report a missing message id', async () => {
            sendEmailSpy.mockResolvedValue({})
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toMatchInlineSnapshot(`"Failed to send email via SES: No messageId returned from SES"`)
        })

        it('should capture a $workflows_email_sent PostHog event on success', async () => {
            jest.spyOn(services.workflowsConfig, 'shouldCaptureEngagementEvents').mockResolvedValue(true)
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
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toHaveLength(0)
        })

        it('should capture a $workflows_email_failed PostHog event on failure', async () => {
            jest.spyOn(services.workflowsConfig, 'shouldCaptureEngagementEvents').mockResolvedValue(true)
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
