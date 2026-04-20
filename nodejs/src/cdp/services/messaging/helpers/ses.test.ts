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
        tags: {
            ph_id: [
                generateEmailTrackingCode({
                    functionId: 'abc123',
                    id: 'inv456',
                    teamId: 1,
                    state: {
                        actionId: 'act789',
                    },
                }),
            ],
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
        expect(result.logEntries).toEqual([
            {
                functionId: 'abc123',
                invocationId: 'inv456',
                actionId: 'act789',
                teamId: '1',
                level: 'info',
                message: '[Action:act789] Opened (UA)',
                timestamp: '2025-10-03T12:01:00Z',
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
        expect(result.logEntries).toEqual([
            {
                functionId: 'abc123',
                invocationId: 'inv456',
                actionId: 'act789',
                teamId: '1',
                level: 'info',
                message: '[Action:act789] Link clicked: https://example.com (UA)',
                timestamp: '2025-10-03T12:02:00Z',
            },
        ])
    })

    it('skips Send events (email_sent is recorded synchronously, not from webhooks)', async () => {
        const body = [{ eventType: 'Send', mail: baseMail }]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics).toHaveLength(0)
    })

    it('parses a raw Delivery event', async () => {
        const body = [
            {
                eventType: 'Delivery',
                mail: baseMail,
                delivery: {
                    timestamp: '2025-10-03T12:03:00Z',
                    smtpResponse: '250 OK',
                    processingTimeMillis: 825,
                    reportingMTA: 'a14-57.smtp-out.amazonses.com',
                },
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
        expect(result.logEntries).toEqual([
            {
                functionId: 'abc123',
                invocationId: 'inv456',
                actionId: 'act789',
                teamId: '1',
                level: 'info',
                message: '[Action:act789] Delivered, 250 OK (825ms, reporting MTA a14-57.smtp-out.amazonses.com)',
                timestamp: '2025-10-03T12:03:00Z',
            },
        ])
    })

    it('emits one log per recipient listed on a Delivery event', async () => {
        const body = [
            {
                eventType: 'Delivery',
                mail: baseMail,
                delivery: {
                    timestamp: '2025-10-03T12:03:00Z',
                    recipients: ['a@example.com', 'b@example.com'],
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.logEntries).toHaveLength(2)
        expect(result.logEntries?.[0].message).toBe('[Action:act789] Delivered to a@example.com')
        expect(result.logEntries?.[1].message).toBe('[Action:act789] Delivered to b@example.com')
    })

    it('parses a raw Bounce event and returns opt-out recipients for permanent bounces', async () => {
        const body = [
            {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [
                        {
                            emailAddress: 'to@example.com',
                            action: 'failed',
                            status: '5.1.1',
                            diagnosticCode: 'mailbox does not exist',
                        },
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
        expect(result.logEntries).toEqual([
            {
                functionId: 'abc123',
                invocationId: 'inv456',
                actionId: 'act789',
                teamId: '1',
                level: 'error',
                message: '[Action:act789] Permanent bounce to to@example.com, mailbox does not exist (5.1.1)',
                timestamp: '2025-10-03T12:04:00Z',
            },
        ])
    })

    it('does not duplicate status when SES inlines it inside diagnosticCode', async () => {
        const body = [
            {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [
                        {
                            emailAddress: 'to@example.com',
                            status: '5.1.1',
                            diagnosticCode: 'smtp; 550 5.1.1 user unknown <to@example.com>',
                        },
                    ],
                    timestamp: '2025-10-03T12:04:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.logEntries?.[0].message).toBe(
            '[Action:act789] Permanent bounce to to@example.com, smtp; 550 5.1.1 user unknown <to@example.com>'
        )
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
        expect(result.logEntries?.[0].level).toBe('warn')
        expect(result.logEntries?.[0].message).toBe('[Action:act789] Transient bounce to to@example.com, temp (4.1.1)')
    })

    it('parses a raw Complaint event', async () => {
        const body = [
            {
                eventType: 'Complaint',
                mail: baseMail,
                complaint: {
                    complainedRecipients: [{ emailAddress: 'to@example.com' }],
                    timestamp: '2025-10-03T12:05:00Z',
                    complaintFeedbackType: 'abuse',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].metricName).toBe('email_blocked')
        expect(result.logEntries).toEqual([
            {
                functionId: 'abc123',
                invocationId: 'inv456',
                actionId: 'act789',
                teamId: '1',
                level: 'warn',
                message: '[Action:act789] Complaint from to@example.com, feedback type: abuse',
                timestamp: '2025-10-03T12:05:00Z',
            },
        ])
    })

    it('does not emit log entries for Send events', async () => {
        const body = [{ eventType: 'Send', mail: baseMail }]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.logEntries).toEqual([])
    })

    it('drops the [Action:...] prefix when actionId contains unsafe characters', async () => {
        // Craft a ph_id whose actionId closes the Action token early and opens an Actor
        // token to exercise the frontend rich-log viewer's link rendering.
        const malicious = generateEmailTrackingCode({
            functionId: 'abc123',
            id: 'inv456',
            teamId: 1,
            state: { actionId: 'act] [Actor:attacker@evil.com' },
        })
        const body = [
            {
                eventType: 'Open',
                mail: { ...baseMail, tags: { ph_id: [malicious] } },
                open: { userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        // Prefix omitted entirely since actionId fails the allowlist
        expect(result.logEntries?.[0].message).toBe('Opened (UA)')
    })

    it('truncates log fan-out when recipient count exceeds MAX_RECIPIENTS_PER_EVENT', async () => {
        const body = [
            {
                eventType: 'Delivery',
                mail: baseMail,
                delivery: {
                    timestamp: '2025-10-03T12:03:00Z',
                    recipients: Array.from({ length: 75 }, (_, i) => `user${i}@example.com`),
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        // Metric is still emitted once per event regardless of recipient count
        expect(result.metrics?.[0].metricName).toBe('email_delivered')
        // 50 per-recipient lines + 1 summary line = 51 total entries
        expect(result.logEntries).toHaveLength(51)
        expect(result.logEntries?.[0].message).toBe('[Action:act789] Delivered to user0@example.com')
        expect(result.logEntries?.[49].message).toBe('[Action:act789] Delivered to user49@example.com')
        expect(result.logEntries?.[50].message).toBe('[Action:act789] ... and 25 more recipients omitted from logs')
    })

    it('preserves full bouncedRecipients list for opt-out even when log fan-out is truncated', async () => {
        const body = [
            {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    timestamp: '2025-10-03T12:04:00Z',
                    bouncedRecipients: Array.from({ length: 55 }, (_, i) => ({
                        emailAddress: `bad${i}@example.com`,
                    })),
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        // Opt-out list covers ALL bounced recipients, not just the first 50
        expect(result.optOutRecipients?.[0].emailAddresses).toHaveLength(55)
        // Log fan-out is capped at 50 + 1 summary line
        expect(result.logEntries).toHaveLength(51)
        expect(result.logEntries?.[50].message).toBe('[Action:act789] ... and 5 more recipients omitted from logs')
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
