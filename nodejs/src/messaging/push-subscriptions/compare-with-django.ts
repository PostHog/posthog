/** Fires the same requests at the Django view and this prototype and diffs status and body.
 *
 * Usage: tsx compare-with-django.ts <django-url> <node-url> <project-token> [app-id]
 */
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

type Case = { name: string; method: string; body: unknown; raw?: boolean; headers?: Record<string, string> }

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
]

function report(line: string): void {
    process.stdout.write(`${line}\n`)
}

async function call(base: string, testCase: Case): Promise<string> {
    const response = await internalFetch(`${base}/api/push_subscriptions/`, {
        method: testCase.method,
        headers: { 'Content-Type': 'application/json', ...(testCase.headers ?? {}) },
        body: testCase.raw ? (testCase.body as string) : JSON.stringify(testCase.body),
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
    report(`\n${cases.length - failures}/${cases.length} identical`)
    process.exit(failures ? 1 : 0)
}

void main()
