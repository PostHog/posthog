import { SesWebhookHandler } from './ses'
import { generateEmailTrackingCode } from './tracking-code'

describe('SesWebhookHandler', () => {
    let handler: SesWebhookHandler
    beforeEach(() => {
        handler = new SesWebhookHandler()
    })

    const baseMail = {
        timestamp: '2025-10-03T12:00:00Z',
        source: 'sender@example.com',
        messageId: 'msg-123',
        destination: ['to@example.com'],
        tags: { ph_id: [generateEmailTrackingCode({ functionId: 'abc123', id: 'inv456' })] },
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

    it('parses a raw Delivery event', async () => {
        const body = [
            {
                eventType: 'Delivery',
                mail: baseMail,
                delivery: {
                    processingTimeMillis: 1000,
                    smtpResponse: '250 OK',
                    reportingMTA: 'mta',
                    timestamp: '2025-10-03T12:03:00Z',
                    recipients: ['to@example.com'],
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].metricName).toBe('email_sent')
    })

    it('parses a raw Bounce event', async () => {
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
                mail: { ...baseMail, tags: {} },
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
