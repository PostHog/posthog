import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { MessageRejected, SendingPausedException, TooManyRequestsException } from '@aws-sdk/client-sesv2'

import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { waitForExpect } from '~/tests/helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
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
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL)
        )
        mockFetch.mockClear()
    })
    afterEach(async () => {
        await closeHub(hub)
    })
    describe('when SES is not configured', () => {
        it('should not crash on construction and should fail explicitly on send', async () => {
            const serviceWithoutSES = new EmailService(
                { sesAccessKeyId: '', sesSecretAccessKey: '', sesRegion: '', sesEndpoint: '' },
                hub.integrationManager,
                new TeamWorkflowsConfigService(hub.postgres),
                hub.ENCRYPTION_SALT_KEYS,
                hub.SITE_URL,
                new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL)
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
