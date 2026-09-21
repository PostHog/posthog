/** Fires the same requests at the Django view and this prototype and diffs status and body.
 *
 * Usage: tsx compare-with-django.ts <django-url> <node-url> <project-token> [app-id]
 */
import { gzipSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

type Case = {
    name: string
    method: string
    body?: unknown
    raw?: boolean
    bytes?: Buffer
    query?: string
    headers?: Record<string, string>
}

const [djangoUrl, nodeUrl, token, appId = 'posthog-dev'] = process.argv.slice(2)

const cases: Case[] = [
    {
        name: 'register ok',
        method: 'POST',
        body: { api_key: token, distinct_id: 'diff-1', device_token: 't', app_id: appId },
    },
    {
        name: 'register with platform field',
        method: 'POST',
        body: { api_key: token, distinct_id: 'diff-1', device_token: 't', app_id: appId, platform: 'android' },
    },
    {
        name: 'unregister ok',
        method: 'DELETE',
        body: { api_key: token, distinct_id: 'diff-1', device_token: 't', app_id: appId },
    },
    {
        name: 'unknown app_id is discarded',
        method: 'POST',
        body: { api_key: token, distinct_id: 'diff-1', device_token: 't', app_id: 'com.nope.nothing' },
    },
    {
        name: 'token via `token` key',
        method: 'POST',
        body: { token, distinct_id: 'diff-1', device_token: 't', app_id: appId },
    },
    {
        name: 'invalid token',
        method: 'POST',
        body: { api_key: 'phc_not_a_real_token', distinct_id: 'd', device_token: 't', app_id: appId },
    },
    { name: 'missing token', method: 'POST', body: { distinct_id: 'd', device_token: 't', app_id: appId } },
    { name: 'missing distinct_id', method: 'POST', body: { api_key: token, device_token: 't', app_id: appId } },
    {
        name: 'empty device_token',
        method: 'POST',
        body: { api_key: token, distinct_id: 'd', device_token: '', app_id: appId },
    },
    {
        name: 'non-string app_id',
        method: 'POST',
        body: { api_key: token, distinct_id: 'd', device_token: 't', app_id: 12 },
    },
    { name: 'all fields missing', method: 'POST', body: { api_key: token } },
    { name: 'invalid json', method: 'POST', body: '{not json', raw: true },
    { name: 'json array body', method: 'POST', body: '[1,2,3]', raw: true },
    { name: 'empty body', method: 'POST', body: '', raw: true },
    { name: 'oversized body', method: 'POST', body: `{"api_key":"x","pad":"${'a'.repeat(17 * 1024)}"}`, raw: true },
    // One chunk larger than anything the reader retains, which is where a truncating read answers
    // `invalid_json` instead of 413.
    {
        name: 'oversized body in one chunk',
        method: 'POST',
        body: `{"api_key":"x","pad":"${'a'.repeat(1024 * 1024)}"}`,
        raw: true,
    },
    {
        name: 'token in properties',
        method: 'POST',
        body: { properties: { token }, distinct_id: 'diff-3', device_token: 't', app_id: appId },
    },
    {
        name: '$token wins over api_key',
        method: 'POST',
        body: { $token: token, api_key: 'phc_bogus', distinct_id: 'diff-3', device_token: 't', app_id: appId },
    },
    {
        name: 'method not allowed',
        method: 'PUT',
        body: { api_key: token, distinct_id: 'd', device_token: 't', app_id: appId },
    },
    {
        name: 'sdk user agent',
        method: 'POST',
        body: { api_key: token, distinct_id: 'diff-2', device_token: 't', app_id: appId },
        headers: { 'User-Agent': 'posthog-android/3.59.0' },
    },
    // Request decoding. Every SDK release in the wild picks one of these encodings and never changes
    // it, so a body Django accepts and this does not is a device that never registers again.
    {
        name: 'gzipped body',
        method: 'POST',
        bytes: gzipSync(
            Buffer.from(JSON.stringify({ api_key: token, distinct_id: 'diff-gz', device_token: 't', app_id: appId }))
        ),
        headers: { 'Content-Encoding': 'gzip' },
    },
    {
        name: 'gzipped body without a content-encoding header',
        method: 'POST',
        bytes: gzipSync(
            Buffer.from(JSON.stringify({ api_key: token, distinct_id: 'diff-gz2', device_token: 't', app_id: appId }))
        ),
    },
    {
        name: 'gzipped body named in the query string',
        method: 'POST',
        bytes: gzipSync(
            Buffer.from(JSON.stringify({ api_key: token, distinct_id: 'diff-gz3', device_token: 't', app_id: appId }))
        ),
        query: '?compression=gzip-js',
    },
    {
        name: 'gzipped DELETE body',
        method: 'DELETE',
        bytes: gzipSync(
            Buffer.from(JSON.stringify({ api_key: token, distinct_id: 'diff-gz', device_token: 't', app_id: appId }))
        ),
        headers: { 'Content-Encoding': 'gzip' },
    },
    {
        name: 'truncated gzip stream',
        method: 'POST',
        bytes: gzipSync(Buffer.from('{"a":1}')).subarray(0, 8),
        headers: { 'Content-Encoding': 'gzip' },
    },
    {
        name: 'the literal string undefined as a gzip body',
        method: 'POST',
        body: 'undefined',
        raw: true,
        headers: { 'Content-Encoding': 'gzip' },
    },
    {
        name: 'base64 body',
        method: 'POST',
        body: Buffer.from(
            JSON.stringify({ api_key: token, distinct_id: 'diff-b64', device_token: 't', app_id: appId })
        ).toString('base64'),
        raw: true,
    },
    {
        name: 'form-encoded body carrying the token as a field',
        method: 'POST',
        body: new URLSearchParams({
            api_key: token,
            data: JSON.stringify({ distinct_id: 'diff-form', device_token: 't', app_id: appId }),
        }).toString(),
        raw: true,
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    },
    {
        name: 'content type with a charset parameter',
        method: 'POST',
        body: { api_key: token, distinct_id: 'diff-ct', device_token: 't', app_id: appId },
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
    },
    {
        name: 'body carrying a python-only numeric constant',
        method: 'POST',
        body: `{"api_key":"${token}","distinct_id":"diff-nan","device_token":"t","app_id":"${appId}","retries":NaN}`,
        raw: true,
    },
    { name: 'empty object body', method: 'POST', body: '{}', raw: true },
    { name: 'bare null body', method: 'POST', body: 'null', raw: true },
    { name: 'invalid utf-8 body', method: 'POST', bytes: Buffer.from([0x7b, 0xff, 0xfe, 0x7d]) },
    // Field handling.
    {
        name: 'a repeated field takes the last value',
        method: 'POST',
        body: `{"api_key":"${token}","distinct_id":"first","distinct_id":"diff-dup","device_token":"t","app_id":"${appId}"}`,
        raw: true,
    },
    {
        name: 'fields offered through the prototype',
        method: 'POST',
        body: `{"__proto__":{"api_key":"${token}"},"distinct_id":"d","device_token":"t","app_id":"${appId}"}`,
        raw: true,
    },
    {
        name: 'unicode distinct_id and device token',
        method: 'POST',
        body: { api_key: token, distinct_id: 'diff-🚀-café', device_token: 'tökén-🔔', app_id: appId },
    },
    {
        name: 'very long app_id',
        method: 'POST',
        body: { api_key: token, distinct_id: 'd', device_token: 't', app_id: 'a'.repeat(2000) },
    },
    {
        name: 'null device_token',
        method: 'POST',
        body: { api_key: token, distinct_id: 'd', device_token: null, app_id: appId },
    },
    {
        name: 'whitespace-only distinct_id',
        method: 'POST',
        body: { api_key: token, distinct_id: '   ', device_token: 't', app_id: appId },
    },
    {
        name: 'unregister for an app the project never configured',
        method: 'DELETE',
        body: { api_key: token, distinct_id: 'diff-1', device_token: 't', app_id: 'com.nope.nothing' },
    },
    // The exact shapes the released SDKs put on the wire, read from posthog-android's
    // PostHogPushSubscriptionRequest and posthog-ios's sendPushSubscription. These are the requests
    // that must not change behaviour, because an app in the field cannot be corrected.
    {
        name: 'sdk: android register',
        method: 'POST',
        body: { api_key: token, distinct_id: 'sdk-android', device_token: 'fcm-token', app_id: appId },
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'posthog-android/3.59.0' },
    },
    {
        name: 'sdk: android unregister',
        method: 'DELETE',
        body: { api_key: token, distinct_id: 'sdk-android', device_token: 'fcm-token', app_id: appId },
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'posthog-android/3.59.0' },
    },
    {
        name: 'sdk: android register carrying an identity token',
        method: 'POST',
        body: {
            api_key: token,
            distinct_id: 'sdk-android',
            device_token: 'fcm-token',
            app_id: appId,
            identity_token: 'not.a.valid.token',
        },
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'User-Agent': 'posthog-android/3.59.0' },
    },
    // iOS gzips every one of these, registration and unregistration alike, and sets no content type.
    {
        name: 'sdk: ios register (gzipped, no content type)',
        method: 'POST',
        bytes: gzipSync(
            Buffer.from(
                JSON.stringify({
                    api_key: token,
                    distinct_id: 'sdk-ios',
                    device_token: 'apns-token',
                    platform: 'ios',
                    app_id: appId,
                })
            )
        ),
        headers: { 'Content-Encoding': 'gzip', 'Content-Type': '', 'User-Agent': 'posthog-ios/3.31.0' },
    },
    {
        name: 'sdk: ios unregister (gzipped)',
        method: 'DELETE',
        bytes: gzipSync(
            Buffer.from(
                JSON.stringify({
                    api_key: token,
                    distinct_id: 'sdk-ios',
                    device_token: 'apns-token',
                    platform: 'ios',
                    app_id: appId,
                })
            )
        ),
        headers: { 'Content-Encoding': 'gzip', 'Content-Type': '', 'User-Agent': 'posthog-ios/3.31.0' },
    },
    {
        name: 'sdk: ios register with the form content type urlsession can default to',
        method: 'POST',
        bytes: gzipSync(
            Buffer.from(
                JSON.stringify({
                    api_key: token,
                    distinct_id: 'sdk-ios-form',
                    device_token: 'apns-token',
                    platform: 'ios',
                    app_id: appId,
                })
            )
        ),
        headers: {
            'Content-Encoding': 'gzip',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'posthog-ios/3.31.0',
        },
    },
    {
        name: 'sdk: ios register against an apns bundle id',
        method: 'POST',
        bytes: gzipSync(
            Buffer.from(
                JSON.stringify({
                    api_key: token,
                    distinct_id: 'sdk-ios-apns',
                    device_token: 'apns-token',
                    platform: 'ios',
                    app_id: 'com.posthog.pushtest',
                })
            )
        ),
        headers: { 'Content-Encoding': 'gzip', 'Content-Type': '', 'User-Agent': 'posthog-ios/3.31.0' },
    },
    { name: 'HEAD is refused', method: 'HEAD', body: '', raw: true },
    { name: 'PATCH is refused', method: 'PATCH', body: '{}', raw: true },
]

function report(line: string): void {
    process.stdout.write(`${line}\n`)
}

/** Headers the two are expected to differ on, with the reason. Everything else differing is a
 * regression: a header is part of the contract just as much as the body, and the status-and-body
 * diff below cannot see one.
 *
 * Every entry here is CORS, which only a browser applies. Android sends this through OkHttp and iOS
 * through URLSession, and neither performs a preflight or checks these headers, so none of these
 * differences can reach a device. They are listed rather than ignored so that a header difference
 * which is not one of these still fails the run. */
const EXPECTED_HEADER_DIFFERENCES: Record<string, string> = {
    'access-control-allow-methods': 'django omits DELETE although it serves it',
    'access-control-allow-headers':
        "django's cors middleware answers the preflight with its own list before the view is reached",
    'access-control-allow-origin': 'django middleware widens this to * on the non-preflight response',
    vary: 'django adds Cookie because its session middleware ran',
}

const COMPARED_HEADERS = [
    'content-type',
    'access-control-allow-origin',
    'access-control-allow-credentials',
    'access-control-allow-methods',
    'access-control-allow-headers',
    'vary',
]

async function headers(base: string, method: string): Promise<Record<string, string>> {
    const response = await internalFetch(`${base}/api/push_subscriptions/`, {
        method,
        headers: { Origin: 'https://app.example.com', 'Content-Type': 'application/json' },
        body: method === 'OPTIONS' ? undefined : '{}',
    })
    const collected: Record<string, string> = {}
    for (const name of COMPARED_HEADERS) {
        collected[name] = response.headers[name] ?? '<absent>'
    }
    return collected
}

async function compareHeaders(): Promise<number> {
    let unexpected = 0
    for (const method of ['OPTIONS', 'POST']) {
        const [django, node] = await Promise.all([headers(djangoUrl, method), headers(nodeUrl, method)])
        for (const name of COMPARED_HEADERS) {
            if (django[name] === node[name]) {
                continue
            }
            const expected = EXPECTED_HEADER_DIFFERENCES[name]
            report(`${expected ? 'NOTE' : 'DIFF'} | ${method} header ${name}`)
            report(`       django: ${django[name]}`)
            report(`       node:   ${node[name]}`)
            if (expected) {
                report(`       expected: ${expected}`)
            } else {
                unexpected++
            }
        }
    }
    return unexpected
}

async function call(base: string, testCase: Case): Promise<string> {
    const body = testCase.bytes ?? (testCase.raw ? (testCase.body as string) : JSON.stringify(testCase.body))
    const response = await internalFetch(`${base}/api/push_subscriptions/${testCase.query ?? ''}`, {
        method: testCase.method,
        headers: { 'Content-Type': 'application/json', ...testCase.headers },
        body: testCase.method === 'HEAD' ? undefined : (body as any),
    })
    const text = await response.text()
    let parsed: unknown = text
    try {
        parsed = parseJSON(text)
    } catch {
        parsed = text.trim()
    }
    return `${response.status} ${JSON.stringify(parsed)}`
}

async function main(): Promise<void> {
    let failures = 0
    for (const testCase of cases) {
        const [django, node] = await Promise.all([call(djangoUrl, testCase), call(nodeUrl, testCase)])
        const same = django === node
        if (!same) {
            failures++
        }
        report(`${same ? 'OK  ' : 'DIFF'} | ${testCase.name}`)
        if (!same) {
            report(`       django: ${django}`)
            report(`       node:   ${node}`)
        }
    }
    report('')
    const headerFailures = await compareHeaders()

    report(`\n${cases.length - failures}/${cases.length} identical`)
    process.exit(failures + headerFailures ? 1 : 0)
}

void main()
