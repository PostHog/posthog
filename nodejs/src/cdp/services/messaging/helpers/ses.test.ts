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

    type SimpleEventCase = {
        name: string
        body: any
        metricName: string | null
        log: { level: string; message: string } | null
        optOutRecipients?: { teamId: string; emailAddresses: string[] }[]
    }
    const simpleEventCases: SimpleEventCase[] = [
        {
            // Info-level events still emit metrics, but no log entries.
            name: 'Open',
            body: {
                eventType: 'Open',
                mail: baseMail,
                open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
            metricName: 'email_opened',
            log: null,
        },
        {
            name: 'Click',
            body: {
                eventType: 'Click',
                mail: baseMail,
                click: {
                    ipAddress: '1.2.3.4',
                    link: 'https://example.com',
                    userAgent: 'UA',
                    timestamp: '2025-10-03T12:02:00Z',
                },
            },
            metricName: 'email_link_clicked',
            log: null,
        },
        {
            name: 'Delivery',
            body: {
                eventType: 'Delivery',
                mail: baseMail,
                delivery: {
                    timestamp: '2025-10-03T12:03:00Z',
                    smtpResponse: '250 OK',
                    processingTimeMillis: 825,
                    reportingMTA: 'a14-57.smtp-out.amazonses.com',
                    recipients: ['a@example.com', 'b@example.com'],
                },
            },
            metricName: 'email_delivered',
            log: null,
        },
        {
            name: 'Bounce permanent',
            body: {
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
            metricName: 'email_bounced',
            log: {
                level: 'error',
                message: '[Action:act789] Permanent bounce to to@example.com, mailbox does not exist (5.1.1)',
            },
            optOutRecipients: [{ teamId: '1', emailAddresses: ['to@example.com'] }],
        },
        {
            name: 'Bounce transient',
            body: {
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
            metricName: 'email_bounced',
            log: {
                level: 'warn',
                message: '[Action:act789] Transient bounce to to@example.com, temp (4.1.1)',
            },
            optOutRecipients: [],
        },
        {
            name: 'Complaint',
            body: {
                eventType: 'Complaint',
                mail: baseMail,
                complaint: {
                    complainedRecipients: [{ emailAddress: 'to@example.com' }],
                    timestamp: '2025-10-03T12:05:00Z',
                    complaintFeedbackType: 'abuse',
                },
            },
            metricName: 'email_blocked',
            log: {
                level: 'warn',
                message: '[Action:act789] Complaint from to@example.com, feedback type: abuse',
            },
        },
        {
            name: 'RenderingFailure',
            body: {
                eventType: 'RenderingFailure',
                mail: baseMail,
                renderingFailure: { errorMessage: 'bad template', templateName: 'welcome' },
            },
            metricName: 'email_failed',
            log: {
                level: 'error',
                message: '[Action:act789] Rendering failure for template welcome: bad template',
            },
        },
        {
            name: 'Reject',
            body: { eventType: 'Reject', mail: baseMail, reject: { reason: 'spam' } },
            metricName: 'email_failed',
            log: {
                level: 'error',
                message: '[Action:act789] Message rejected by SES: spam',
            },
        },
        {
            // email_sent is recorded synchronously when the email is sent, so the Send
            // webhook is intentionally a no-op (no metric, no log) to avoid double counting.
            name: 'Send (skip)',
            body: { eventType: 'Send', mail: baseMail },
            metricName: null,
            log: null,
        },
        {
            // DeliveryDelay is accepted so SNS doesn't retry, but not surfaced as a log
            // (SES retries soft failures on its own).
            name: 'DeliveryDelay (accepted, not logged)',
            body: {
                eventType: 'DeliveryDelay',
                mail: baseMail,
                deliveryDelay: {
                    delayType: 'MailboxFull',
                    timestamp: '2025-10-03T12:06:00Z',
                    delayedRecipients: [{ emailAddress: 'to@example.com' }],
                },
            },
            metricName: null,
            log: null,
        },
    ]

    it.each(simpleEventCases)('parses a raw $name event', async ({ body, metricName, log, optOutRecipients }) => {
        const result = await handler.handleWebhook({ body: [body], headers: {} })
        expect(result.status).toBe(200)
        expect(result.body).toEqual({ ok: true })

        if (metricName) {
            expect(result.metrics).toEqual([
                { functionId: 'abc123', invocationId: 'inv456', actionId: 'act789', metricName },
            ])
        } else {
            expect(result.metrics).toEqual([])
        }

        if (log) {
            expect(result.logEntries).toEqual([
                {
                    functionId: 'abc123',
                    invocationId: 'inv456',
                    actionId: 'act789',
                    teamId: '1',
                    level: log.level,
                    message: log.message,
                },
            ])
        } else {
            expect(result.logEntries).toEqual([])
        }

        if (optOutRecipients !== undefined) {
            expect(result.optOutRecipients).toEqual(optOutRecipients)
        }
    })

    it('emits one log per bounced recipient', async () => {
        const body = [
            {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    timestamp: '2025-10-03T12:04:00Z',
                    bouncedRecipients: [
                        { emailAddress: 'a@example.com', diagnosticCode: 'mailbox full' },
                        { emailAddress: 'b@example.com', diagnosticCode: 'mailbox full' },
                    ],
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.logEntries).toHaveLength(2)
        expect(result.logEntries?.[0].message).toBe('[Action:act789] Permanent bounce to a@example.com, mailbox full')
        expect(result.logEntries?.[1].message).toBe('[Action:act789] Permanent bounce to b@example.com, mailbox full')
        expect(result.optOutRecipients?.[0].emailAddresses).toEqual(['a@example.com', 'b@example.com'])
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
                eventType: 'Bounce',
                mail: { ...baseMail, tags: { ph_id: [malicious] } },
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [{ emailAddress: 'to@example.com', diagnosticCode: 'unknown' }],
                    timestamp: '2025-10-03T12:04:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        // Prefix omitted entirely since actionId fails the allowlist
        expect(result.logEntries?.[0].message).toBe('Permanent bounce to to@example.com, unknown')
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

    it('propagates parentRunId from the tracking code so batch runs get correct attribution', async () => {
        const mailWithParentRun = {
            ...baseMail,
            tags: {
                ph_id: [
                    generateEmailTrackingCode({
                        functionId: 'workflow-id',
                        id: 'child-invocation-id',
                        teamId: 1,
                        parentRunId: 'batch-run-id',
                        state: { actionId: 'email-action' },
                    }),
                ],
            },
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
