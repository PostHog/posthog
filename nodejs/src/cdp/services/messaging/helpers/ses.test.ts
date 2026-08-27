import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'

import { SesWebhookHandler, normalizeClickUrl, resolveClickDestination } from './ses'
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

    it('unwraps a legacy redirect link and surfaces the SES link tag', async () => {
        const body = [
            {
                eventType: 'Click',
                mail: baseMail,
                click: {
                    link: `http://localhost:8010/public/m/redirect?ph_id=${signer.generate(
                        baseInvocation
                    )}&target=${encodeURIComponent('https://example.com/pricing?a=1')}`,
                    linkTags: { phl: ['2'] },
                    timestamp: '2025-10-03T12:02:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.metrics?.[0].properties).toEqual({
            $email_to: 'to@example.com',
            $link_url: 'https://example.com/pricing?a=1',
            $link_index: '2',
        })
    })

    it('emits a per-link companion metric keyed by action, link index and normalized url', async () => {
        const body = [
            {
                eventType: 'Click',
                mail: baseMail,
                click: {
                    link: 'https://example.com/pricing/?utm_content=hero&uid=abc',
                    linkTags: { phl: ['3'] },
                    timestamp: '2025-10-03T12:02:00Z',
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        // The rollup keeps its own name so existing totals and trends can't double-count the
        // per-link row, and the query string is dropped so per-recipient values don't fragment it.
        expect(result.metrics?.map((m) => [m.metricName, m.instanceIdOverride])).toEqual([
            ['email_link_clicked', undefined],
            ['email_link_clicked_by_link', 'act789|3|https://example.com/pricing'],
        ])
    })

    it('skips the per-link metric when the send has no action id', async () => {
        const noActionInvocation = { functionId: 'abc123', id: 'inv456', teamId: 1 } as const
        const body = [
            {
                eventType: 'Click',
                mail: {
                    ...baseMail,
                    headers: [{ name: TRACKING_CODE_HEADER, value: signer.generate(noActionInvocation) }],
                    tags: undefined,
                },
                click: { link: 'https://example.com/a', timestamp: '2025-10-03T12:02:00Z' },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        // Without an action id the key would fall back to the invocation id, producing one row per
        // send per link instead of an aggregate.
        expect(result.metrics?.map((m) => m.metricName)).toEqual(['email_link_clicked'])
    })

    describe('normalizeClickUrl', () => {
        it.each([
            ['drops the query string', 'https://example.com/a?b=1', 'https://example.com/a'],
            ['drops the fragment', 'https://example.com/a#top', 'https://example.com/a'],
            ['drops a trailing slash', 'https://example.com/a/', 'https://example.com/a'],
            ['keeps the path', 'https://example.com/a/b/c', 'https://example.com/a/b/c'],
            ['passes through a hostless scheme', 'mailto:x', 'mailto:x'],
            ['passes through an unparseable link', 'not a url', 'not a url'],
        ])('%s', (_name, link, expected) => {
            expect(normalizeClickUrl(link)).toBe(expected)
        })

        // Per-recipient tokens in the path would otherwise land in the metrics sort key, making its
        // cardinality scale with audience size and putting recipient secrets in a team-readable store.
        it.each([
            [
                'a uuid',
                'https://example.com/verify/123e4567-e89b-12d3-a456-426614174000',
                'https://example.com/verify/*',
            ],
            [
                'a long hex digest',
                'https://example.com/unsubscribe/a1b2c3d4e5f6a7b8',
                'https://example.com/unsubscribe/*',
            ],
            ['a bare numeric id', 'https://example.com/users/1234567', 'https://example.com/users/*'],
            [
                'a long opaque token',
                'https://example.com/magic/AbCdEfGhIjKlMnOpQrStUvWx',
                'https://example.com/magic/*',
            ],
            [
                'a dot-separated jwt',
                'https://example.com/reset/eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CV',
                'https://example.com/reset/*',
            ],
            [
                'a percent-encoded token',
                'https://example.com/verify/%31%32%33e4567-e89b-12d3-a456-426614174000',
                'https://example.com/verify/*',
            ],
            ['a mixed-case token', 'https://example.com/m/aB3xK9mZq2LpW7fT', 'https://example.com/m/*'],
            [
                'a token carrying base64url separators',
                'https://example.com/m/aB3-xK9_mZq2LpW7fT5vN8cR1jH4gY6s',
                'https://example.com/m/*',
            ],
        ])('redacts %s from the path', (_name, link, expected) => {
            expect(normalizeClickUrl(link)).toBe(expected)
        })

        // Over-redacting empties the breakdown of the very thing it exists to show, so slugs long
        // enough to resemble a token have to survive.
        it.each([
            ['a hyphenated slug', 'https://example.com/blog/how-to-set-up-feature-flags'],
            ['a title-cased slug', 'https://example.com/blog/Getting-Started-With-PostHog'],
            ['an unbroken lowercase word', 'https://example.com/docs/gettingstartedguide'],
            ['a dated filename', 'https://example.com/files/annual-report-2026.pdf'],
            ['a short path word', 'https://example.com/pricing/enterprise-plan'],
        ])('keeps %s', (_name, link) => {
            expect(normalizeClickUrl(link)).toBe(link)
        })

        it('caps the length so a long url cannot bloat the metrics sort key', () => {
            // Many short segments, because a single long segment is collapsed by the redaction above
            // and would never reach the cap.
            expect(normalizeClickUrl(`https://example.com/${'ab/'.repeat(100)}`)).toHaveLength(200)
        })
    })

    describe('resolveClickDestination', () => {
        it.each([
            ['a destination link is passed through', 'https://example.com/x?a=1', 'https://example.com/x?a=1'],
            [
                'a redirect wrapper resolves to its target',
                'https://webhooks.us.posthog.com/public/m/redirect?ph_id=abc.def&target=https%3A%2F%2Fexample.com%2Fx',
                'https://example.com/x',
            ],
            [
                'a redirect wrapper with no target falls back to the raw link',
                'https://webhooks.us.posthog.com/public/m/redirect?ph_id=abc.def',
                'https://webhooks.us.posthog.com/public/m/redirect?ph_id=abc.def',
            ],
            ['an unparseable link is passed through', 'not a url', 'not a url'],
        ])('%s', (_name, link, expected) => {
            expect(resolveClickDestination(link)).toBe(expected)
        })
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

    it('does not suppress recipients on a permanent bounce for test sends', async () => {
        // Editor "Run test" traffic must not be able to suppress a production address just by
        // targeting a bad recipient — the isTest gate on suppressionAllowed blocks the write.
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
        expect(result.metrics).toEqual([])
        expect(result.logEntries).toEqual([])
        expect(result.hardBounceRecipients).toEqual([])
    })

    it.each([
        [
            'Transient bounce',
            {
                eventType: 'Bounce',
                bounce: {
                    bounceType: 'Transient',
                    bouncedRecipients: [{ emailAddress: 'to@example.com', diagnosticCode: 'temp' }],
                    timestamp: '2025-10-03T12:04:00Z',
                },
            },
            'transientBounceRecipients' as const,
        ],
        [
            'Delivery',
            {
                eventType: 'Delivery',
                delivery: { timestamp: '2025-10-03T12:04:00Z', recipients: ['to@example.com'] },
            },
            'deliveredRecipients' as const,
        ],
        [
            'Complaint',
            {
                eventType: 'Complaint',
                complaint: {
                    complainedRecipients: [{ emailAddress: 'to@example.com' }],
                    timestamp: '2025-10-03T12:05:00Z',
                },
            },
            'complainedRecipients' as const,
        ],
    ])('does not populate %s suppression writes for test sends', async (_label, eventFields, arrayKey) => {
        // Same guarantee as the permanent-bounce test above but for the other state-changing
        // events: a "Run test" from the editor must not push into the suppression counter
        // (transient), reset it (delivery), or suppress outright (complaint), which could
        // otherwise perturb production suppression state.
        const testMail = {
            ...baseMail,
            headers: [{ name: TRACKING_CODE_HEADER, value: signer.generate(baseInvocation, true) }],
            tags: { ph_id: [signer.generateShort(baseInvocation)] },
        }
        const result = await handler.handleWebhook({ body: [{ mail: testMail, ...eventFields }], headers: {} })
        expect(result[arrayKey]).toEqual([])
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

    it('parses a raw Bounce event and surfaces permanent bounces for suppression', async () => {
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
        // Hard bounces emit both the catch-all metric and the AWS-comparable hard-only one
        expect(result.metrics?.map((m) => m.metricName)).toEqual(['email_bounced', 'email_bounced_hard'])
        expect(result.metrics?.[0].distinctId).toBe('user-123')
        expect(result.hardBounceRecipients).toEqual([
            { teamId: '1', emailAddresses: ['to@example.com'], diagnostic: 'bad' },
        ])
        expect(result.transientBounceRecipients).toEqual([])
    })

    it('surfaces transient bounces for the soft-bounce counter, not the hard-bounce list', async () => {
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
        // Transient bounces must NOT emit email_bounced_hard — AWS's account rate excludes them
        expect(result.metrics?.map((m) => m.metricName)).toEqual(['email_bounced', 'email_bounced_transient'])
        expect(result.metrics?.[0].distinctId).toBe('user-123')
        expect(result.hardBounceRecipients).toEqual([])
        expect(result.transientBounceRecipients).toEqual([
            { teamId: '1', emailAddresses: ['to@example.com'], diagnostic: 'temp' },
        ])
    })

    it('surfaces delivered recipients so the suppression counter can reset', async () => {
        const body = [
            {
                eventType: 'Delivery',
                mail: baseMail,
                delivery: {
                    timestamp: '2025-10-03T12:04:00Z',
                    recipients: ['to@example.com'],
                },
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(result.deliveredRecipients).toEqual([
            { teamId: '1', emailAddresses: ['to@example.com'], timestamp: '2025-10-03T12:04:00Z' },
        ])
        expect(result.transientBounceRecipients).toEqual([])
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
        expect(result.hardBounceRecipients).toBeUndefined()
    })

    it.each([
        // A registered spam complaint surfaces the recipient for suppression.
        {
            feedbackType: 'abuse',
            expectedRecipients: [{ teamId: '1', emailAddresses: ['to@example.com'], feedbackType: 'abuse' }],
        },
        // "not-spam" is a correction, not a complaint, so the recipient must not be suppressed. The
        // metric still counts the event.
        { feedbackType: 'not-spam', expectedRecipients: [] },
    ])(
        'parses a raw Complaint event with feedback type "$feedbackType" and surfaces the right recipients',
        async ({ feedbackType, expectedRecipients }) => {
            const body = [
                {
                    eventType: 'Complaint',
                    mail: baseMail,
                    complaint: {
                        complainedRecipients: [{ emailAddress: 'to@example.com' }],
                        timestamp: '2025-10-03T12:05:00Z',
                        complaintFeedbackType: feedbackType,
                    },
                },
            ]
            const result = await handler.handleWebhook({ body, headers: {} })
            expect(result.status).toBe(200)
            expect(result.metrics?.[0].metricName).toBe('email_blocked')
            expect(result.metrics?.[0].distinctId).toBe('user-123')
            expect(result.metrics?.[0].properties).toMatchObject({ $complaint_feedback_type: feedbackType })
            expect(result.complainedRecipients).toEqual(expectedRecipients)
        }
    )

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

    it('labels a dropped record "missing" when no code is present and "invalid" when it is present but unparseable', async () => {
        // Read the specific label combination as a delta, so accumulation from other tests in the
        // process cannot make this assertion flaky.
        const droppedCount = async (reason: string): Promise<number> => {
            const metric = await register.getSingleMetric('email_tracking_unattributed_total')!.get()
            return metric.values.find((v) => v.labels.event_type === 'Open' && v.labels.reason === reason)?.value ?? 0
        }
        const missingBefore = await droppedCount('missing')
        const invalidBefore = await droppedCount('invalid')

        const open = { ipAddress: '1.2.3.4', userAgent: 'UA', timestamp: '2025-10-03T12:01:00Z' }
        const body = [
            // Neither carrier holds a value: the code is missing.
            { eventType: 'Open', mail: { ...baseMail, tags: {}, headers: [] }, open },
            // A signed header is present but its signature no longer verifies (e.g. after a signing
            // key rotated out): the code is present but invalid, and this incident must not read as a
            // carrier loss.
            {
                eventType: 'Open',
                mail: {
                    ...baseMail,
                    tags: {},
                    headers: [{ name: TRACKING_CODE_HEADER, value: 'stale-payload.badsignature' }],
                },
                open,
            },
        ]
        const result = await handler.handleWebhook({ body, headers: {} })
        expect(result.status).toBe(200)
        expect(await droppedCount('missing')).toBe(missingBefore + 1)
        expect(await droppedCount('invalid')).toBe(invalidBefore + 1)
    })

    // Real SNS SubscriptionConfirmation shape: SubscribeURL is a top-level envelope field and
    // Message is human-readable text, not JSON.
    const buildConfirmationEnvelope = (subscribeUrl: string): Record<string, any> => ({
        Type: 'SubscriptionConfirmation',
        MessageId: 'sns-msg-1',
        Token: 'token-123',
        TopicArn: 'arn:aws:sns:us-east-1:123456789012:ses-topic',
        Message:
            'You have chosen to subscribe to the topic arn:aws:sns:us-east-1:123456789012:ses-topic.\nTo confirm the subscription, visit the SubscribeURL included in this message.',
        SubscribeURL: subscribeUrl,
        Timestamp: '2025-10-03T12:10:00Z',
        SignatureVersion: '1',
        Signature: 'fake',
        SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
    })

    it('confirms SubscriptionConfirmation with valid SNS SubscribeURL', async () => {
        const fetchSpy = jest.spyOn(handler as any, 'fetchText').mockResolvedValue('')
        const snsEnvelope = buildConfirmationEnvelope(
            'https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:us-east-1:123456789012:ses-topic&Token=token-123'
        )
        const result = await handler.handleWebhook({ body: snsEnvelope, headers: {}, verifySignature: false })
        expect(result.status).toBe(200)
        expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('https://sns.us-east-1.amazonaws.com/'))
        fetchSpy.mockRestore()
    })

    it('confirms a signed SubscriptionConfirmation end to end (SubscribeURL is part of the signed string)', async () => {
        const { generateKeyPairSync, createSign } = jest.requireActual<typeof import('node:crypto')>('node:crypto')
        const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 })
        const publicKeyPem = publicKey.export({ type: 'spki', format: 'pem' }).toString()

        const envelope = buildConfirmationEnvelope(
            'https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:us-east-1:123456789012:ses-topic&Token=token-123'
        )
        // String to sign per AWS SNS SignatureVersion=1 for SubscriptionConfirmation:
        // alphabetical key/value lines incl. the top-level SubscribeURL.
        const stringToSign =
            ['Message', 'MessageId', 'SubscribeURL', 'Timestamp', 'Token', 'TopicArn', 'Type']
                .map((k) => `${k}\n${envelope[k]}`)
                .join('\n') + '\n'
        const sign = createSign('RSA-SHA1')
        sign.update(stringToSign, 'utf8')
        envelope.Signature = sign.sign(privateKey, 'base64')

        const fetchSpy = jest
            .spyOn(handler as any, 'fetchText')
            .mockImplementation((url) => Promise.resolve((url as string).endsWith('.pem') ? publicKeyPem : ''))

        const result = await handler.handleWebhook({ body: envelope, headers: {}, verifySignature: true })
        expect(result.status).toBe(200)
        expect(fetchSpy).toHaveBeenCalledWith(envelope.SubscribeURL)
        fetchSpy.mockRestore()
    })

    it.each([
        ['non-SNS SubscribeURL', 'https://evil.lhr.life/latest/meta-data/iam/security-credentials/role'],
        ['HTTP SubscribeURL', 'http://sns.us-east-1.amazonaws.com/subscribe'],
    ])('rejects SubscriptionConfirmation with %s', async (_label, subscribeUrl) => {
        const result = await handler.handleWebhook({
            body: buildConfirmationEnvelope(subscribeUrl),
            headers: {},
            verifySignature: false,
        })
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

    describe('security: TopicArn allowlist + signed-code gate', () => {
        // Two-layer hardening: the TopicArn allowlist restricts which SNS topics we accept events from,
        // and state-changing writes require a signed tracking code (unsigned carriers only contribute
        // to engagement metrics/log entries).
        const buildEnvelope = (
            topicArn: string,
            innerRecord: object,
            envelopeType: 'Notification' | 'SubscriptionConfirmation' = 'Notification'
        ): Record<string, any> => ({
            Type: envelopeType,
            MessageId: 'sns-msg-1',
            TopicArn: topicArn,
            Message:
                envelopeType === 'Notification'
                    ? JSON.stringify(innerRecord)
                    : `You have chosen to subscribe to the topic ${topicArn}.`,
            ...(envelopeType === 'SubscriptionConfirmation'
                ? {
                      Token: 'token-123',
                      SubscribeURL: 'https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription',
                  }
                : {}),
            Timestamp: '2025-10-03T12:10:00Z',
            SignatureVersion: '1',
            Signature: 'stubbed',
            SigningCertURL: 'https://sns.us-east-1.amazonaws.com/cert.pem',
        })

        it('rejects a Notification whose TopicArn is not on the allowlist', async () => {
            const restricted = new SesWebhookHandler(signer, ['arn:aws:sns:us-east-1:123456789012:allowed-topic'])
            const envelope = buildEnvelope('arn:aws:sns:us-east-1:999999999999:other-topic', {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [{ emailAddress: 'recipient@example.com', diagnosticCode: 'bad' }],
                    timestamp: '2025-10-03T12:04:00Z',
                },
            })
            const result = await restricted.handleWebhook({ body: envelope, headers: {}, verifySignature: false })
            expect(result.status).toBe(403)
            expect(result.hardBounceRecipients).toBeUndefined()
        })

        it('accepts a Notification whose TopicArn matches the allowlist', async () => {
            const restricted = new SesWebhookHandler(signer, ['arn:aws:sns:us-east-1:123456789012:allowed-topic'])
            const envelope = buildEnvelope('arn:aws:sns:us-east-1:123456789012:allowed-topic', {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [{ emailAddress: 'recipient@example.com', diagnosticCode: 'bad' }],
                    timestamp: '2025-10-03T12:04:00Z',
                },
            })
            const result = await restricted.handleWebhook({ body: envelope, headers: {}, verifySignature: false })
            expect(result.status).toBe(200)
            expect(result.hardBounceRecipients).toEqual([
                { teamId: '1', emailAddresses: ['recipient@example.com'], diagnostic: 'bad' },
            ])
        })

        it('empty allowlist means no restriction (dev/test backward compat)', async () => {
            // The default `handler` in the outer beforeEach was constructed without an allowlist.
            const envelope = buildEnvelope('arn:aws:sns:us-east-1:999999999999:some-topic', {
                eventType: 'Bounce',
                mail: baseMail,
                bounce: {
                    bounceType: 'Permanent',
                    bouncedRecipients: [{ emailAddress: 'to@example.com', diagnosticCode: 'bad' }],
                    timestamp: '2025-10-03T12:04:00Z',
                },
            })
            const result = await handler.handleWebhook({ body: envelope, headers: {}, verifySignature: false })
            expect(result.status).toBe(200)
        })

        it('rejects a SubscriptionConfirmation from a disallowed topic', async () => {
            const restricted = new SesWebhookHandler(signer, ['arn:aws:sns:us-east-1:123456789012:allowed-topic'])
            const envelope = buildEnvelope(
                'arn:aws:sns:us-east-1:999999999999:other-topic',
                {},
                'SubscriptionConfirmation'
            )
            const result = await restricted.handleWebhook({ body: envelope, headers: {}, verifySignature: false })
            expect(result.status).toBe(403)
        })

        it('does not populate suppression writes for an unsigned tracking code', async () => {
            // Only signed tracking codes drive state changes. Unsigned codes still contribute to
            // metrics/log entries (engagement signal) but not to suppression / opt-out / delivery resets.
            const unsignedMail = {
                ...baseMail,
                headers: undefined,
                tags: { ph_id: [signer.generateShort(baseInvocation)] },
            }
            const body = [
                {
                    eventType: 'Bounce',
                    mail: unsignedMail,
                    bounce: {
                        bounceType: 'Transient',
                        bouncedRecipients: [{ emailAddress: 'soft-bounce@example.com', diagnosticCode: 'temp' }],
                        timestamp: '2025-10-03T12:04:00Z',
                    },
                },
                {
                    eventType: 'Bounce',
                    mail: unsignedMail,
                    bounce: {
                        bounceType: 'Permanent',
                        bouncedRecipients: [{ emailAddress: 'hard-bounce@example.com', diagnosticCode: 'bad' }],
                        timestamp: '2025-10-03T12:04:00Z',
                    },
                },
                {
                    eventType: 'Delivery',
                    mail: unsignedMail,
                    delivery: { timestamp: '2025-10-03T12:05:00Z', recipients: ['delivered@example.com'] },
                },
                {
                    eventType: 'Complaint',
                    mail: unsignedMail,
                    complaint: {
                        complainedRecipients: [{ emailAddress: 'complainer@example.com' }],
                        timestamp: '2025-10-03T12:06:00Z',
                    },
                },
            ]
            const result = await handler.handleWebhook({ body, headers: {} })
            expect(result.status).toBe(200)
            expect(result.transientBounceRecipients).toEqual([])
            expect(result.hardBounceRecipients).toEqual([])
            expect(result.complainedRecipients).toEqual([])
            expect(result.deliveredRecipients).toEqual([])
            // Metrics are unaffected — engagement signal is still emitted for the parsed events.
            expect(result.metrics?.length).toBeGreaterThan(0)
        })
    })
})
