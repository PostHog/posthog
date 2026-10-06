import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { LocalSes } from '~/tests/helpers/ses'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from './email-suppression.service'
import { EmailService } from './email.service'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

describe('EmailService with local SES', () => {
    let hub: Hub
    let service: EmailService
    let invocation: CyclotronJobInvocationHogFunction
    let params: CyclotronInvocationQueueParametersEmailType
    let ses: LocalSes
    const originalEnv = { ...process.env }

    const createService = (endpoint: string): EmailService =>
        new EmailService(
            {
                sesAccessKeyId: 'local-ses-test',
                sesSecretAccessKey: 'local-ses-test',
                sesRegion: 'us-east-1',
                sesEndpoint: endpoint,
                sesTrackedConfigurationSet: 'local-tracked',
                sesUntrackedConfigurationSet: 'local-untracked',
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
            new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
            new RecipientsManagerService(hub.postgres)
        )

    beforeEach(async () => {
        process.env.AWS_ACCESS_KEY_ID = 'local-ses-test'
        process.env.AWS_SECRET_ACCESS_KEY = 'local-ses-test'
        delete process.env.AWS_SESSION_TOKEN
        process.env.AWS_MAX_ATTEMPTS = '1'
        ses = new LocalSes()
        await ses.start()
        hub = await createHub({ SITE_URL: 'http://localhost:8000' })
        const { team } = await createTestTeamFixture(hub.postgres)
        const integration = await insertIntegration(hub.postgres, team.id, {
            kind: 'email',
            config: {
                email: 'sender@example.com',
                name: 'Example Sender',
                domain: 'example.com',
                verified: true,
                provider: 'ses',
            },
        })
        service = createService(ses.endpoint)
        invocation = createExampleInvocation({ team_id: team.id, metadata: { tracking_enabled: false } })
        params = {
            type: 'email',
            from: { integrationId: integration.id },
            to: { email: `${invocation.id}@example.com`, name: 'Example Recipient' },
            cc: 'copy@example.com',
            bcc: 'hidden@example.com',
            replyTo: 'reply@example.com',
            subject: 'Local SES delivery',
            text: 'A plain text message.',
            html: '<p>An HTML message.</p>',
        }
        invocation.queueParameters = params
    })

    afterEach(async () => {
        service?.sesV2Client?.destroy()
        await ses?.stop()
        if (hub) {
            await closeHub(hub)
        }
        process.env = { ...originalEnv }
    })

    it('delivers the email through the real SDK with bodies, addresses and custom headers', async () => {
        const result = await service.executeSendEmail(invocation)

        expect(result).toMatchObject({ finished: true })
        expect(result.error).toBeUndefined()
        expect(result.metrics).toEqual(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'email_sent', count: 1 })])
        )
        expect(ses.requests).toHaveLength(1)
        expect(ses.requests[0]).toMatchObject({
            TenantName: `team-${invocation.teamId}`,
            ConfigurationSetName: 'local-untracked',
            FeedbackForwardingEmailAddress: 'sender@example.com',
            EmailTags: [{ Name: 'ph_id', Value: expect.any(String) }],
        })
        const emails = await ses.getEmails()
        expect(emails).toHaveLength(1)
        expect(emails[0]).toMatchObject({
            messageId: expect.any(String),
            from: '"Example Sender" <sender@example.com>',
            destination: {
                to: [`"Example Recipient" <${params.to.email}>`],
                cc: ['copy@example.com'],
                bcc: ['hidden@example.com'],
            },
            replyTo: ['reply@example.com'],
            subject: 'Local SES delivery',
            body: { text: 'A plain text message.', html: '<p>An HTML message.</p>' },
            headers: expect.arrayContaining([
                { name: 'Auto-Submitted', value: 'auto-generated' },
                { name: 'List-Unsubscribe-Post', value: 'List-Unsubscribe=One-Click' },
                { name: 'List-Unsubscribe', value: expect.stringContaining('http') },
                { name: 'X-PostHog-Tracking-Code', value: expect.any(String) },
            ]),
        })
    })

    it.each([1, 3])('reschedules after %i SDK attempt(s) and sends its email payload on retry', async (attempts) => {
        process.env.AWS_MAX_ATTEMPTS = String(attempts)
        service.sesV2Client?.destroy()
        service = createService(ses.endpoint)
        ses.setError('TooManyRequestsException')
        invocation.queuePriority = 1

        const throttled = await service.executeSendEmail(invocation)

        expect(throttled).toMatchObject({ finished: false, metrics: [] })
        expect(throttled.error).toBeUndefined()
        expect(throttled.invocation.queueParameters).toEqual(params)
        expect(throttled.invocation.queuePriority).toBe(1)
        expect(throttled.invocation.queueScheduledAt?.isValid).toBe(true)
        expect(ses.requests).toHaveLength(attempts)
        expect(await ses.getEmails()).toEqual([])

        ses.setError(undefined)
        const retry = await service.executeSendEmail(throttled.invocation)

        expect(retry).toMatchObject({ finished: true })
        expect(retry.error).toBeUndefined()
        expect(retry.metrics).toEqual(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'email_sent', count: 1 })])
        )
        expect(ses.requests).toHaveLength(attempts + 1)
        expect(ses.requests[attempts]).toMatchObject({
            FromEmailAddress: '"Example Sender" <sender@example.com>',
            Destination: {
                ToAddresses: [`"Example Recipient" <${params.to.email}>`],
                CcAddresses: ['copy@example.com'],
                BccAddresses: ['hidden@example.com'],
            },
            Content: {
                Simple: {
                    Subject: { Data: 'Local SES delivery', Charset: 'UTF-8' },
                    Body: {
                        Text: { Data: 'A plain text message.', Charset: 'UTF-8' },
                        Html: { Data: '<p>An HTML message.</p>', Charset: 'UTF-8' },
                    },
                },
            },
        })
        expect(await ses.getEmails()).toEqual([
            expect.objectContaining({ subject: 'Local SES delivery', body: { text: params.text, html: params.html } }),
        ])
    })

    it.each(['LimitExceededException', 'SendingPausedException'] as const)(
        'fails an HTTP %s without rescheduling or delivering mail',
        async (error) => {
            ses.setError(error)

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({
                finished: true,
                error: `Failed to send email via SES: Local SES injected ${error}`,
                metrics: [expect.objectContaining({ metric_name: 'email_failed', count: 1 })],
            })
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(ses.requests).toHaveLength(1)
            expect(await ses.getEmails()).toEqual([])
        }
    )

    it('isolates concurrent proxy faults and inbox reads for identical recipients', async () => {
        const otherSes = new LocalSes()
        await otherSes.start()
        const otherService = createService(otherSes.endpoint)
        ses.setError('TooManyRequestsException')

        try {
            const [throttled, delivered] = await Promise.all([
                service.executeSendEmail(invocation),
                otherService.executeSendEmail(invocation),
            ])
            expect(throttled).toMatchObject({ finished: false, metrics: [] })
            expect(delivered).toMatchObject({ finished: true })
            expect(delivered.error).toBeUndefined()
            expect(await ses.getEmails()).toEqual([])
            const otherEmails = await otherSes.getEmails()
            expect(otherEmails).toHaveLength(1)

            ses.setError(undefined)
            const retry = await service.executeSendEmail(throttled.invocation)
            expect(retry.error).toBeUndefined()
            const emails = await ses.getEmails()
            expect(emails).toHaveLength(1)
            expect(emails[0].destination).toEqual(otherEmails[0].destination)
            expect(emails[0].messageId).not.toBe(otherEmails[0].messageId)
            expect(await otherSes.getEmails()).toEqual(otherEmails)
            expect(ses.requests).toHaveLength(2)
            expect(otherSes.requests).toHaveLength(1)
        } finally {
            otherService.sesV2Client?.destroy()
            await otherSes.stop()
        }
    })
})
