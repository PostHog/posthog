import { defaultConfig } from '~/common/config/config'

import { SesWebhookHandler } from './ses'
import { EmailTrackingCodeSigner } from './tracking-code'

// Hardcoded (not imported) so a change to the header constant fails this test.
const TRACKING_CODE_HEADER = 'X-PostHog-Tracking-Code'

const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, 'http://localhost:8010')

describe('SesWebhookHandler', () => {
    let handler: SesWebhookHandler
    beforeEach(() => {
        handler = new SesWebhookHandler(signer)
    })

    // Mirrors what the sender writes: the custom header carries the full signed code (including
    // distinct_id, the authoritative source), the SES tag carries the short unsigned code
    // (no distinct_id) as a fallback. The parser prefers the header.
    const baseInvocation = {
        functionId: 'abc123',
        id: 'inv456',
        teamId: 1,
        state: { actionId: 'act789' },
        distinctId: 'user-123',
    } as const

    const baseMail = {
        timestamp: '2025-10-03T12:00:00Z',
        source: 'sender@example.com',
        messageId: 'msg-123',
        destination: ['to@example.com'],
        headers: [{ name: TRACKING_CODE_HEADER, value: signer.generate(baseInvocation) }],
        tags: {
            ph_id: [signer.generateShort(baseInvocation)],
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
                distinctId: 'user-123',
                metricName: 'email_opened',
                properties: { $email_to: 'to@example.com' },
                timestamp: '2025-10-03T12:01:00Z',
            },
        ])
    })

    it('includes $email_subject from the SES commonHeaders', async () => {
        const mailWithSubject = { ...baseMail, commonHeaders: { subject: 'Welcome aboard' } }
        const body = [
            {
                eventType: 'Open',
                mail: mailWithSubject,
                open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].properties).toMatchObject({
            $email_to: 'to@example.com',
            $email_subject: 'Welcome aboard',
        })
    })

    it('parses a raw Click event with link URL', async () => {
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
        expect(result.metrics?.[0].distinctId).toBe('user-123')
        expect(result.metrics?.[0].properties).toEqual({
            $email_to: 'to@example.com',
            $link_url: 'https://example.com',
        })
        expect(result.metrics?.[0].timestamp).toBe('2025-10-03T12:02:00Z')
    })

    it('parses tracking code from header only when SES tag is absent', async () => {
        // Simulates a future state where the EmailTag backwards-compat carrier has been removed.
        const headerOnlyMail = {
            ...baseMail,
            tags: undefined,
        }
        const body = [
            {
                eventType: 'Open',
                mail: headerOnlyMail,
                open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].functionId).toBe('abc123')
        expect(result.metrics?.[0].invocationId).toBe('inv456')
        expect(result.metrics?.[0].distinctId).toBe('user-123')
    })

    it('falls back to SES tag when the custom header is absent (in-flight backwards compat)', async () => {
        // Simulates a webhook for a message sent before the header carrier was rolled out,
        // or arriving from an environment where IncludeOriginalHeaders is not yet enabled
        // on the SES configuration set. The tag still carries the (pre-distinct_id) shape.
        const tagOnlyMail = {
            ...baseMail,
            headers: undefined,
        }
        const body = [
            {
                eventType: 'Open',
                mail: tagOnlyMail,
                open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].functionId).toBe('abc123')
        expect(result.metrics?.[0].invocationId).toBe('inv456')
        // distinct_id is omitted because the short tag carrier doesn't include it.
        expect(result.metrics?.[0].distinctId).toBeUndefined()
    })

    it('prefers the custom header over the SES tag when both are present', async () => {
        // Header carries the canonical (full) code; tag carries the short code as a fallback.
        // The parser must read from the header so distinct_id is recovered.
        const result = await handler.handleWebhook({
            body: [
                {
                    eventType: 'Open',
                    mail: baseMail,
                    open: { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' },
                },
            ],
            headers: {},
        })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].distinctId).toBe('user-123')
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

    // The `if (metricName && !isTest)` guard applies to every metric-emitting event type, so
    // suppression must hold for all of them — not just Delivery.
    it.each([
        ['Open', { open: { timestamp: 't' } }],
        ['Click', { click: { link: 'l', timestamp: 't' } }],
        ['Delivery', { delivery: { timestamp: 't' } }],
    ])('skips metrics for test sends on a %s event (isTest tracking code)', async (eventType, eventFields) => {
        const testMail = {
            ...baseMail,
            // isTest rides on the signed header code (preferred by the webhook); the short tag
            // code stays legacy-shaped without it.
            headers: [{ name: TRACKING_CODE_HEADER, value: signer.generate(baseInvocation, true) }],
            tags: { ph_id: [signer.generateShort(baseInvocation)] },
        }
        const body = [{ eventType, mail: testMail, ...eventFields }]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics).toEqual([])
    })

    it('still opts out recipients on a permanent bounce even for test sends', async () => {
        const testMail = {
            ...baseMail,
            // isTest rides on the signed header code (preferred by the webhook); the short tag
            // code stays legacy-shaped without it.
            headers: [{ name: TRACKING_CODE_HEADER, value: signer.generate(baseInvocation, true) }],
            tags: { ph_id: [signer.generateShort(baseInvocation)] },
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
        // No metric or log entry recorded for the test send, but the hard bounce still triggers an opt-out.
        expect(result.metrics).toEqual([])
        expect(result.logEntries).toEqual([])
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
                distinctId: 'user-123',
                metricName: 'email_delivered',
                properties: { $email_to: 'to@example.com' },
                timestamp: '2025-10-03T12:03:00Z',
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
        expect(result.metrics?.[0].distinctId).toBe('user-123')
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
        expect(result.metrics?.[0].distinctId).toBe('user-123')
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
        expect(result.metrics?.[0].distinctId).toBe('user-123')
    })

    it('returns 200 and no metrics if tracking code is missing from both carriers', async () => {
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
            headers: [{ name: TRACKING_CODE_HEADER, value: signer.generate(batchInvocation) }],
            tags: { ph_id: [signer.generateShort(batchInvocation)] },
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
                properties: { $email_to: 'to@example.com' },
                timestamp: '2025-10-03T12:01:00Z',
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

    describe('log entries', () => {
        const logCases: { name: string; event: Record<string, any>; level: string; message: string }[] = [
            {
                name: 'Bounce permanent',
                event: {
                    eventType: 'Bounce',
                    mail: baseMail,
                    bounce: {
                        bounceType: 'Permanent',
                        bouncedRecipients: [
                            {
                                emailAddress: 'to@example.com',
                                status: '5.1.1',
                                diagnosticCode: 'mailbox does not exist',
                            },
                        ],
                        timestamp: '2025-10-03T12:04:00Z',
                    },
                },
                level: 'error',
                message: '[Action:act789] Permanent bounce to to@example.com, mailbox does not exist (5.1.1)',
            },
            {
                name: 'Bounce transient',
                event: {
                    eventType: 'Bounce',
                    mail: baseMail,
                    bounce: {
                        bounceType: 'Transient',
                        bouncedRecipients: [
                            { emailAddress: 'to@example.com', status: '4.1.1', diagnosticCode: 'temp' },
                        ],
                        timestamp: '2025-10-03T12:04:00Z',
                    },
                },
                level: 'warn',
                message: '[Action:act789] Transient bounce to to@example.com, temp (4.1.1)',
            },
            {
                name: 'Complaint',
                event: {
                    eventType: 'Complaint',
                    mail: baseMail,
                    complaint: {
                        complainedRecipients: [{ emailAddress: 'to@example.com' }],
                        timestamp: '2025-10-03T12:05:00Z',
                        complaintFeedbackType: 'abuse',
                    },
                },
                level: 'warn',
                message: '[Action:act789] Complaint from to@example.com, feedback type: abuse',
            },
            {
                name: 'RenderingFailure',
                event: {
                    eventType: 'RenderingFailure',
                    mail: baseMail,
                    renderingFailure: { errorMessage: 'bad template', templateName: 'welcome' },
                },
                level: 'error',
                message: '[Action:act789] Rendering failure for template welcome: bad template',
            },
            {
                name: 'Reject',
                event: { eventType: 'Reject', mail: baseMail, reject: { reason: 'spam' } },
                level: 'error',
                message: '[Action:act789] Message rejected by SES: spam',
            },
        ]

        it.each(logCases)('emits a $name log entry', async ({ event, level, message }) => {
            const result = await handler.handleWebhook({ body: [event], headers: {} })
            expect(result.logEntries).toEqual([
                expect.objectContaining({ functionId: 'abc123', invocationId: 'inv456', level, message }),
            ])
        })

        it.each([
            { name: 'Open', event: { eventType: 'Open', mail: baseMail, open: { timestamp: '2025-10-03T12:01:00Z' } } },
            {
                name: 'Delivery',
                event: { eventType: 'Delivery', mail: baseMail, delivery: { timestamp: '2025-10-03T12:03:00Z' } },
            },
            { name: 'Send', event: { eventType: 'Send', mail: baseMail } },
        ])('does not emit a log entry for the info-level $name event', async ({ event }) => {
            const result = await handler.handleWebhook({ body: [event], headers: {} })
            expect(result.logEntries).toEqual([])
        })

        it('emits one log entry per bounced recipient', async () => {
            const body = [
                {
                    eventType: 'Bounce',
                    mail: baseMail,
                    bounce: {
                        bounceType: 'Permanent',
                        bouncedRecipients: [
                            { emailAddress: 'a@example.com', diagnosticCode: 'mailbox full' },
                            { emailAddress: 'b@example.com', diagnosticCode: 'mailbox full' },
                        ],
                        timestamp: '2025-10-03T12:04:00Z',
                    },
                },
            ]
            const result = await handler.handleWebhook({ body, headers: {} })
            expect(result.logEntries?.map((e) => e.message)).toEqual([
                '[Action:act789] Permanent bounce to a@example.com, mailbox full',
                '[Action:act789] Permanent bounce to b@example.com, mailbox full',
            ])
        })

        it('does not duplicate the status when SES inlines it inside diagnosticCode', async () => {
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

        it('drops the [Action:...] prefix when the actionId contains unsafe characters', async () => {
            // A ph_id whose actionId would close the Action token early and inject an Actor token
            // must not reach the rich-log viewer with brackets intact.
            const maliciousInvocation = {
                ...baseInvocation,
                state: { actionId: 'act] [Actor:attacker@evil.com' },
            }
            const maliciousMail = {
                ...baseMail,
                headers: [{ name: TRACKING_CODE_HEADER, value: signer.generate(maliciousInvocation) }],
                tags: { ph_id: [signer.generateShort(maliciousInvocation)] },
            }
            const body = [
                {
                    eventType: 'Bounce',
                    mail: maliciousMail,
                    bounce: {
                        bounceType: 'Permanent',
                        bouncedRecipients: [{ emailAddress: 'to@example.com', diagnosticCode: 'unknown' }],
                        timestamp: '2025-10-03T12:04:00Z',
                    },
                },
            ]
            const result = await handler.handleWebhook({ body, headers: {} })
            expect(result.logEntries?.[0].message).toBe('Permanent bounce to to@example.com, unknown')
        })

        it('accepts DeliveryDelay without producing a metric or log (so SNS does not retry)', async () => {
            const body = [
                {
                    eventType: 'DeliveryDelay',
                    mail: baseMail,
                    deliveryDelay: {
                        delayType: 'MailboxFull',
                        timestamp: '2025-10-03T12:06:00Z',
                        delayedRecipients: [{ emailAddress: 'to@example.com' }],
                    },
                },
            ]
            const result = await handler.handleWebhook({ body, headers: {} })
            expect(result.status).toBe(200)
            expect(result.metrics).toEqual([])
            expect(result.logEntries).toEqual([])
        })
    })
})
