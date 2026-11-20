import type { CaptureResult } from 'posthog-js'

import { redactSensitiveUrl, redactSensitiveUrls, replayBlockClassFor } from './sensitiveUrlRedaction'

const USER = '0190f1a2-3b4c-7d5e-8f60-718293a4b5c6'
const INVITE = '0190f1a2-9c8b-7a69-8584-736251403f2e'
const OTHER_INVITE = '0190f1a2-1111-7222-8333-444455556666'
const TOKEN = 'cxmplq-0123456789abcdef0123456789abcdef'
const RESET_URL = `https://us.posthog.com/reset/${USER}/${TOKEN}`
const INVITE_URL = `https://us.posthog.com/signup/${INVITE}`
const REDACTED_BODY = '[SessionRecording] body redacted as might contain an invite'

function capture(fields: Partial<CaptureResult>): CaptureResult {
    return { uuid: 'example', event: '$pageview', properties: {}, ...fields } as CaptureResult
}

describe('redactSensitiveUrl', () => {
    it.each([
        ['a password reset link', RESET_URL, `https://us.posthog.com/reset/${USER}/:token`],
        ['a two-factor reset link', `/reset_2fa/${USER}/${TOKEN}?x=1`, `/reset_2fa/${USER}/:token?x=1`],
        ['an email verification link', `/verify_email/${USER}/${TOKEN}`, `/verify_email/${USER}/:token`],
        ['an invite link', INVITE_URL, 'https://us.posthog.com/signup/:id'],
        ['an invite request', `/api/signup/${INVITE}/`, '/api/signup/:id/'],
        ['a reset request', `/api/reset/${USER}/?token=${TOKEN}`, `/api/reset/${USER}/?token=:token`],
        [
            'a two-factor reset request',
            `https://us.posthog.com/api/reset_2fa/${USER}/?a=1&token=${TOKEN}&b=2`,
            `https://us.posthog.com/api/reset_2fa/${USER}/?a=1&token=:token&b=2`,
        ],
        ['an encoded redirect to an invite', `/login?next=%2Fsignup%2F${INVITE}`, '/login?next=%2Fsignup%2F:id'],
        [
            'an encoded redirect to a reset',
            `/login?next=%2Freset%2F${USER}%2F${TOKEN}`,
            `/login?next=%2Freset%2F${USER}%2F:token`,
        ],
        [
            'a social login link that returns to a two-factor reset',
            `/login/google-oauth2/?next=%2Freset_2fa%2F${USER}%2F${TOKEN}`,
            `/login/google-oauth2/?next=%2Freset_2fa%2F${USER}%2F:token`,
        ],
        [
            'an element chain',
            `a:attr__href="/signup/${INVITE}"href="/signup/${INVITE}"nth-child="1"`,
            'a:attr__href="/signup/:id"href="/signup/:id"nth-child="1"',
        ],
        [
            'element text',
            `Copy https://us.posthog.com/signup/${INVITE.toUpperCase()} to share`,
            'Copy https://us.posthog.com/signup/:id to share',
        ],
    ])('replaces the secret in %s', (_name, text, expected) => {
        expect(redactSensitiveUrl(text)).toBe(expected)
    })

    it.each([
        `/verify_email/${USER}`,
        `/verify_email/${USER}?reason=x`,
        '/signup',
        '/api/signup/precheck',
        '/reset',
        `/reset/${USER}/:token`,
        '/signup/:id',
        'https://us.posthog.com/project/1/insights',
    ])('keeps %s', (text) => {
        expect(redactSensitiveUrl(text)).toBe(text)
    })

    it('scans a long text without a token in linear time', () => {
        const text = `/reset/${USER}/?next=`.repeat(20_000)

        const start = performance.now()
        expect(redactSensitiveUrl(text)).toBe(text)
        expect(performance.now() - start).toBeLessThan(1000)
    })
})

describe('replayBlockClassFor', () => {
    it('blocks a link whose URL holds a secret', () => {
        expect(replayBlockClassFor(`/login/google-oauth2/?next=%2Freset_2fa%2F${USER}%2F${TOKEN}`)).toBe(
            'ph-replay-block'
        )
    })

    it('leaves other links in replay', () => {
        expect(replayBlockClassFor('/login/google-oauth2/?next=%2Fproject%2F1')).toBeUndefined()
    })
})

describe('redactSensitiveUrls', () => {
    it('redacts the event properties', () => {
        const event = redactSensitiveUrls(
            capture({
                properties: {
                    $current_url: RESET_URL,
                    $pathname: `/reset/${USER}/${TOKEN}`,
                    $referrer: INVITE_URL,
                    $session_entry_url: INVITE_URL,
                    $web_vitals_LCP_event: { $current_url: RESET_URL },
                    $elements_chain: `a:attr__href="/signup/${INVITE}"`,
                    kept: 1,
                },
            })
        )

        expect(event?.properties).toEqual({
            $current_url: `https://us.posthog.com/reset/${USER}/:token`,
            $pathname: `/reset/${USER}/:token`,
            $referrer: 'https://us.posthog.com/signup/:id',
            $session_entry_url: 'https://us.posthog.com/signup/:id',
            $web_vitals_LCP_event: { $current_url: `https://us.posthog.com/reset/${USER}/:token` },
            $elements_chain: 'a:attr__href="/signup/:id"',
            kept: 1,
        })
    })

    it('redacts the initial URL person properties', () => {
        const event = redactSensitiveUrls(
            capture({
                $set: { $current_url: INVITE_URL },
                $set_once: { $initial_current_url: RESET_URL, $initial_pathname: `/signup/${INVITE}` },
            })
        )

        expect(event?.$set).toEqual({ $current_url: 'https://us.posthog.com/signup/:id' })
        expect(event?.$set_once).toEqual({
            $initial_current_url: `https://us.posthog.com/reset/${USER}/:token`,
            $initial_pathname: '/signup/:id',
        })
    })

    it('merges the heatmap data of URLs that redact to the same value', () => {
        const event = redactSensitiveUrls(
            capture({
                event: '$$heatmap',
                properties: {
                    $heatmap_data: {
                        [INVITE_URL]: [{ x: 1 }],
                        [`https://us.posthog.com/signup/${OTHER_INVITE}`]: [{ x: 2 }],
                        'https://us.posthog.com/project/1': [{ x: 3 }],
                    },
                },
            })
        )

        expect(event?.properties.$heatmap_data).toEqual({
            'https://us.posthog.com/signup/:id': [{ x: 1 }, { x: 2 }],
            'https://us.posthog.com/project/1': [{ x: 3 }],
        })
    })

    it('redacts the strings in replay snapshots', () => {
        const event = redactSensitiveUrls(
            capture({
                event: '$snapshot',
                properties: {
                    $snapshot_data: [
                        { type: 4, data: { href: INVITE_URL, width: 1, height: 1 }, timestamp: 1 },
                        { type: 5, data: { tag: '$url_changed', payload: { href: RESET_URL } }, timestamp: 2 },
                        {
                            type: 6,
                            data: {
                                plugin: 'rrweb/network@1',
                                payload: {
                                    requests: [
                                        {
                                            name: `https://us.posthog.com/api/reset/${USER}/?token=${TOKEN}`,
                                            responseStatus: 400,
                                        },
                                    ],
                                },
                            },
                            timestamp: 3,
                        },
                    ],
                },
            })
        )

        expect(event?.properties.$snapshot_data).toEqual([
            { type: 4, data: { href: 'https://us.posthog.com/signup/:id', width: 1, height: 1 }, timestamp: 1 },
            {
                type: 5,
                data: { tag: '$url_changed', payload: { href: `https://us.posthog.com/reset/${USER}/:token` } },
                timestamp: 2,
            },
            {
                type: 6,
                data: {
                    plugin: 'rrweb/network@1',
                    payload: {
                        requests: [
                            { name: `https://us.posthog.com/api/reset/${USER}/?token=:token`, responseStatus: 400 },
                        ],
                    },
                },
                timestamp: 3,
            },
        ])
    })

    it('removes the bodies of invite requests from replay snapshots', () => {
        const otherRequest = { name: 'https://us.posthog.com/api/projects/1/insights/', responseBody: '{"results":[]}' }
        const event = redactSensitiveUrls(
            capture({
                event: '$snapshot',
                properties: {
                    $snapshot_data: [
                        {
                            type: 6,
                            data: {
                                plugin: 'rrweb/network@1',
                                payload: {
                                    requests: [
                                        {
                                            name: `https://us.posthog.com/api/signup/${INVITE}/`,
                                            responseBody: JSON.stringify({ id: INVITE }),
                                        },
                                        {
                                            name: 'https://us.posthog.com/api/organizations/@current/invites/',
                                            requestBody: '{"target_email":"someone@example.com"}',
                                            responseBody: JSON.stringify({ results: [{ id: INVITE }] }),
                                        },
                                        otherRequest,
                                    ],
                                },
                            },
                            timestamp: 1,
                        },
                    ],
                },
            })
        )

        const requests = event?.properties.$snapshot_data[0].data.payload.requests
        expect(requests).toEqual([
            {
                name: 'https://us.posthog.com/api/signup/:id/',
                responseBody: REDACTED_BODY,
            },
            {
                name: 'https://us.posthog.com/api/organizations/@current/invites/',
                requestBody: REDACTED_BODY,
                responseBody: REDACTED_BODY,
            },
            otherRequest,
        ])
        expect(requests[2]).toBe(otherRequest)
        expect(JSON.stringify(event)).not.toContain(INVITE)
    })

    it('returns the same event when nothing needs redaction', () => {
        const event = capture({
            event: '$snapshot',
            properties: {
                $current_url: 'https://us.posthog.com/project/1',
                $snapshot_data: [{ type: 4, data: { href: 'https://us.posthog.com/verify_email/' + USER } }],
            },
            $set_once: { $initial_pathname: '/project/1' },
        })

        expect(redactSensitiveUrls(event)).toBe(event)
    })

    it('redacts an object each time it appears', () => {
        const shared = { href: INVITE_URL }
        const event = redactSensitiveUrls(capture({ properties: { first: shared, second: [shared] } }))

        expect(event?.properties).toEqual({
            first: { href: 'https://us.posthog.com/signup/:id' },
            second: [{ href: 'https://us.posthog.com/signup/:id' }],
        })
    })

    it('redacts an object that refers to itself', () => {
        const looped: Record<string, unknown> = { href: INVITE_URL }
        looped.self = looped

        const event = redactSensitiveUrls(capture({ properties: { looped } }))

        expect(event?.properties.looped.href).toBe('https://us.posthog.com/signup/:id')
    })
})
