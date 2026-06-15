import { SesWebhookHandler } from './ses'
import { generateEmailTrackingCode, generateShortEmailTrackingCode } from './tracking-code'

// Hardcoded (not imported) so a change to the header constant fails this test.
const TRACKING_CODE_HEADER = 'X-PostHog-Tracking-Code'

describe('SesWebhookHandler', () => {
    let handler: SesWebhookHandler
    beforeEach(() => {
        handler = new SesWebhookHandler()
    })

    // Mirrors what the sender writes: the custom header carries the full signed code (the
    // authoritative source), the SES tag carries the short unsigned code as a fallback.
    const baseInvocation = {
        functionId: 'abc123',
        id: 'inv456',
        teamId: 1,
        state: { actionId: 'act789' },
    } as const

    const baseMail = {
        timestamp: '2025-10-03T12:00:00Z',
        source: 'sender@example.com',
        messageId: 'msg-123',
        destination: ['to@example.com'],
        headers: [{ name: TRACKING_CODE_HEADER, value: generateEmailTrackingCode(baseInvocation) }],
        tags: {
            ph_id: [generateShortEmailTrackingCode(baseInvocation)],
        },
    }

    it('parses a raw Open event', async () => {
        const body = [
            {
                eventType: 'Open',
                mail: baseMail,
                open: {
                    ipAddress: '1.2.3.4',
                    userAgent: 'UA',
                    timestamp: '2025-10-03T12:01:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.body).toEqual({ ok: true })
        expect(result.metrics).toEqual([
            {
                functionId: 'abc123',
                invocationId: 'inv456',
                actionId: 'act789',
                metricName: 'email_opened',
            },
        ])
    })

    it('parses a raw Click event', async () => {
        const body = [
            {
                eventType: 'Click',
                mail: baseMail,
                click: {
                    ipAddress: '1.2.3.4',
                    link: 'https://example.com',
                    userAgent: 'UA',
                    timestamp: '2025-10-03T12:02:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].metricName).toBe('email_link_clicked')
    })

    it('skips Send events (email_sent is recorded synchronously, not from webhooks)', async () => {
        const body = [{ eventType: 'Send', mail: baseMail }]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics).toHaveLength(0)
    })

    it('parses the signed code from the header when the SES tag is absent', async () => {
        const headerOnlyMail = { ...baseMail, tags: undefined }
        const body = [
            {
                eventType: 'Open',
                mail: headerOnlyMail,
                open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0]).toMatchObject({ functionId: 'abc123', invocationId: 'inv456' })
    })

    it('falls back to the SES tag when the custom header is absent (in-flight backwards compat)', async () => {
        const tagOnlyMail = { ...baseMail, headers: undefined }
        const body = [
            {
                eventType: 'Open',
                mail: tagOnlyMail,
                open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0]).toMatchObject({ functionId: 'abc123', invocationId: 'inv456' })
    })

    it('skips metrics for test sends (isTest tracking code)', async () => {
        const testMail = {
            ...baseMail,
            headers: [{ name: TRACKING_CODE_HEADER, value: generateEmailTrackingCode(baseInvocation, true) }],
            tags: { ph_id: [generateShortEmailTrackingCode(baseInvocation, true)] },
        }
        const body = [
            {
                eventType: 'Delivery',
                mail: testMail,
                delivery: { timestamp: '2025-10-03T12:03:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics).toEqual([])
    })

    it('still opts out recipients on a permanent bounce even for test sends', async () => {
        const testMail = {
            ...baseMail,
            headers: [{ name: TRACKING_CODE_HEADER, value: generateEmailTrackingCode(baseInvocation, true) }],
            tags: { ph_id: [generateShortEmailTrackingCode(baseInvocation, true)] },
        }
        const body = [
            {
                eventType: 'Bounce',
                mail: testMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [
                        { emailAddress: 'to@example.com', action: 'failed', status: '5.1.1', diagnosticCode: 'bad' },
                    ],
                    timestamp: '2025-10-03T12:04:00Z',
                    reportingMTA: 'mta',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        // No metric recorded for the test send, but the hard bounce still triggers an opt-out.
        expect(result.metrics).toEqual([])
        expect(result.optOutRecipients).toEqual([{ teamId: '1', emailAddresses: ['to@example.com'] }])
    })

    it('parses a raw Delivery event', async () => {
        const body = [
            {
                eventType: 'Delivery',
                mail: baseMail,
                delivery: { timestamp: '2025-10-03T12:03:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics).toEqual([
            {
                functionId: 'abc123',
                invocationId: 'inv456',
                actionId: 'act789',
                metricName: 'email_delivered',
            },
        ])
    })

    it('parses a raw Bounce event and returns opt-out recipients for permanent bounces', async () => {
        const body = [
            {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [
                        { emailAddress: 'to@example.com', action: 'failed', status: '5.1.1', diagnosticCode: 'bad' },
                    ],
                    timestamp: '2025-10-03T12:04:00Z',
                    reportingMTA: 'mta',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].metricName).toBe('email_bounced')
        expect(result.optOutRecipients).toEqual([{ teamId: '1', emailAddresses: ['to@example.com'] }])
    })

    it('does not return opt-out recipients for transient bounces', async () => {
        const body = [
            {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Transient',
                    bouncedRecipients: [
                        { emailAddress: 'to@example.com', action: 'failed', status: '4.1.1', diagnosticCode: 'temp' },
                    ],
                    timestamp: '2025-10-03T12:04:00Z',
                    reportingMTA: 'mta',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].metricName).toBe('email_bounced')
        expect(result.optOutRecipients).toEqual([])
    })

    it('rejects raw (non-SNS) deliveries when signature verification is required', async () => {
        const body = [
            {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [
                        {
                            emailAddress: 'victim@example.com',
                            action: 'failed',
                            status: '5.1.1',
                            diagnosticCode: 'bad',
                        },
                    ],
                    timestamp: '2025-10-03T12:04:00Z',
                    reportingMTA: 'mta',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {}, verifySignature: true })
        expect(result.status).toBe(403)
        expect(result.optOutRecipients).toBeUndefined()
    })

    it('parses a raw Complaint event', async () => {
        const body = [
            {
                eventType: 'Complaint',
                mail: baseMail,
                complaint: {
                    complainedRecipients: [{ emailAddress: 'to@example.com' }],
                    timestamp: '2025-10-03T12:05:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].metricName).toBe('email_blocked')
    })

    it('returns 200 and no metrics if tracking code is missing', async () => {
        const body = [
            {
                eventType: 'Open',
                mail: { ...baseMail, tags: {}, headers: [] },
                open: {
                    ipAddress: '1.2.3.4',
                    userAgent: 'UA',
                    timestamp: '2025-10-03T12:01:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics).toEqual([])
    })

    it('confirms SubscriptionConfirmation with valid SNS SubscribeURL', async () => {
        const fetchSpy = jest.spyOn(handler as any, 'fetchText').mockResolvedValue('')
        const snsEnvelope = {
            Type: 'SubscriptionConfirmation',
            MessageId: 'sns-msg-1',
            Token: 'token-123',
            TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-topic',
            Message: JSON.stringify({
                SubscribeURL:
                    'https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:us-east-1:123456789012:ses-topic&Token=token-123',
            }),
            Timestamp: '2025-10-03T12:10:00Z',
            SignatureVersion: '1',
            Signature: 'fake',
            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
        }
        const result = await handler.handleWebhook({ body: snsEnvelope, headers: {}, verifySignature: false })
        expect(result.status).toBe(200)
        expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('https://sns.us-east-1.amazonaws.com/'))
        fetchSpy.mockRestore()
    })

    it('rejects SubscriptionConfirmation with non-SNS SubscribeURL', async () => {
        const snsEnvelope = {
            Type: 'SubscriptionConfirmation',
            MessageId: 'sns-msg-1',
            Token: 'token-123',
            TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-topic',
            Message: JSON.stringify({
                SubscribeURL: 'https://evil.lhr.life/latest/meta-data/iam/security-credentials/role',
            }),
            Timestamp: '2025-10-03T12:10:00Z',
            SignatureVersion: '1',
            Signature: 'fake',
            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
        }
        const result = await handler.handleWebhook({ body: snsEnvelope, headers: {}, verifySignature: false })
        expect(result.status).toBe(403)
    })

    it('rejects SubscriptionConfirmation with HTTP SubscribeURL', async () => {
        const snsEnvelope = {
            Type: 'SubscriptionConfirmation',
            MessageId: 'sns-msg-1',
            Token: 'token-123',
            TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-topic',
            Message: JSON.stringify({
                SubscribeURL: 'http://sns.us-east-1.amazonaws.com/subscribe',
            }),
            Timestamp: '2025-10-03T12:10:00Z',
            SignatureVersion: '1',
            Signature: 'fake',
            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
        }
        const result = await handler.handleWebhook({ body: snsEnvelope, headers: {}, verifySignature: false })
        expect(result.status).toBe(403)
    })

    it('propagates parentRunId from the tracking code so batch runs get correct attribution', async () => {
        const batchInvocation = {
            functionId: 'workflow-id',
            id: 'child-invocation-id',
            teamId: 1,
            parentRunId: 'batch-run-id',
            state: { actionId: 'email-action' },
        }
        const mailWithParentRun = {
            ...baseMail,
            headers: [{ name: TRACKING_CODE_HEADER, value: generateEmailTrackingCode(batchInvocation) }],
            tags: { ph_id: [generateShortEmailTrackingCode(batchInvocation)] },
        }
        const body = [
            {
                eventType: 'Open',
                mail: mailWithParentRun,
                open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics).toEqual([
            {
                functionId: 'workflow-id',
                invocationId: 'child-invocation-id',
                actionId: 'email-action',
                parentRunId: 'batch-run-id',
                metricName: 'email_opened',
            },
        ])
    })

    it('parses an SNS envelope Notification event', async () => {
        const snsEnvelope = {
            Type: 'Notification',
            MessageId: 'sns-msg-1',
            TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-topic',
            Message: JSON.stringify({
                eventType: 'Open',
                mail: baseMail,
                open: {
                    ipAddress: '1.2.3.4',
                    userAgent: 'UA',
                    timestamp: '2025-10-03T12:01:00Z',
                },
            }),
            Timestamp: '2025-10-03T12:10:00Z',
            SignatureVersion: '1',
            Signature: 'fake',
            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
        }
        const result = await handler.handleWebhook({ body: snsEnvelope, headers: {}, verifySignature: false })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].metricName).toBe('email_opened')
    })
})
