import { describe, expect, test } from 'bun:test'

import { runHog, type HogRun } from '@/testing'

const TELEMETRY = 'https://us.i.posthog.com/batch/'
const ON = { telemetryToken: 'phc_test' }
const AGENT = { CLAUDECODE: '1' }

function feedbackEvents(result: HogRun): { distinct_id: string; properties: Record<string, unknown> }[] {
    return result.requests
        .filter((request) => request.url === TELEMETRY)
        .flatMap((request: any) => request.body.batch)
        .filter((event: any) => event.event === 'cli feedback submitted')
}

describe('hog feedback', () => {
    test('sends a cli feedback event, with the first line as the summary', async () => {
        const result = await runHog(
            [
                'feedback',
                'hog query run cuts off long values\nA column with JSON in it ends after 40 characters.',
                '--sentiment',
                'negative',
                '--area',
                'hog query run',
                '--suggestion',
                'Wrap long values',
            ],
            { ...ON, env: AGENT, respond: () => ({ status: 200, body: {} }) }
        )

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({
            sent: true,
            dryRun: false,
            identified: false,
            type: 'cli',
            sentiment: 'negative',
            summary: 'hog query run cuts off long values',
            details: 'hog query run cuts off long values\nA column with JSON in it ends after 40 characters.',
        })
        expect(feedbackEvents(result)).toEqual([
            expect.objectContaining({
                properties: expect.objectContaining({
                    feedback_summary: 'hog query run cuts off long values',
                    feedback_details:
                        'hog query run cuts off long values\nA column with JSON in it ends after 40 characters.',
                    feedback_type: 'cli',
                    feedback_sentiment: 'negative',
                    feedback_product_area: 'hog query run',
                    feedback_suggested_improvement: 'Wrap long values',
                    cli: 'hog',
                    agent: 'claude-code',
                }),
            }),
        ])
    })

    test('sends feedback with telemetry off, without the install ID or the usage event', async () => {
        const result = await runHog(['feedback', 'The skills list is useful', '--no-telemetry'], {
            ...ON,
            env: AGENT,
            respond: () => ({ status: 200, body: {} }),
        })

        expect(result.exitCode).toBe(0)
        const events = result.requests.filter((request) => request.url === TELEMETRY).flatMap((r: any) => r.body.batch)
        expect(events.map((event: any) => event.event)).toEqual(['cli feedback submitted'])
        expect(events[0].properties).not.toHaveProperty('install_id')
        expect(events[0].properties).not.toHaveProperty('$groups')
        expect(result.files['/home/test/.posthog/hog-telemetry-id']).toBeUndefined()
    })

    test.each([
        ['telemetry on', []],
        ['telemetry off', ['--no-telemetry']],
    ])('anonymous feedback with %s never carries the install ID an earlier login linked', async (_name, flags) => {
        const result = await runHog(['feedback', 'hog is slow to start', ...flags], {
            ...ON,
            env: AGENT,
            files: { '/home/test/.posthog/hog-telemetry-id': 'linked-install-id\n' },
            respond: () => ({ status: 200, body: {} }),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ sent: true, identified: false })
        const [event] = feedbackEvents(result)
        expect(event?.distinct_id).not.toBe('linked-install-id')
        expect(event?.properties).not.toHaveProperty('install_id')
    })

    test('feedback from a stored login belongs to that PostHog user', async () => {
        const host = 'https://us.posthog.com'
        const result = await runHog(['feedback', 'hog is slow to start'], {
            ...ON,
            env: AGENT,
            files: {
                '/home/test/.config/hog/settings.json': JSON.stringify({
                    logins: {
                        [host]: { '42': { store: 'keychain', type: 'personal_api_key', projectId: '42', host } },
                    },
                    host,
                }),
            },
            keychain: { [`${host}#42`]: JSON.stringify({ apiKey: 'phx_secret' }) },
            respond: (url) =>
                url.endsWith('/api/users/@me/')
                    ? { status: 200, body: { distinct_id: 'user-distinct-id', organization: { id: 'org-1' } } }
                    : url.endsWith('/api/projects/42/')
                      ? { status: 200, body: { organization: 'org-1', uuid: 'project-uuid' } }
                      : { status: 200, body: {} },
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ sent: true, identified: true })
        expect(feedbackEvents(result)[0]?.distinct_id).toBe('user-distinct-id')
    })

    test('fails when PostHog does not take the feedback', async () => {
        const result = await runHog(['feedback', 'hog is slow to start'], {
            ...ON,
            env: AGENT,
            respond: () => ({ status: 503, body: {} }),
        })

        expect(result.exitCode).toBe(1)
        expect(result.error().code).toBe('feedback_not_sent')
    })

    test.each([
        ['no feedback', ['feedback'], 'missing_feedback'],
        ['feedback over the limit', ['feedback', 'x'.repeat(5001)], 'feedback_too_long'],
    ])('%s is a usage error and sends nothing', async (_name, argv, code) => {
        const result = await runHog(argv, { ...ON, env: AGENT, respond: () => ({ status: 200, body: {} }) })

        expect(result.exitCode).toBe(2)
        expect(result.error().code).toBe(code)
        expect(feedbackEvents(result)).toEqual([])
    })

    test('a person at the terminal is asked for the feedback', async () => {
        const result = await runHog(['feedback'], {
            ...ON,
            stdoutIsTTY: true,
            answers: ['The login page is clear'],
            respond: () => ({ status: 200, body: {} }),
        })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain('Sent your feedback to the PostHog team')
        expect(feedbackEvents(result)[0]?.properties.feedback_summary).toBe('The login page is clear')
    })

    test('--dry-run sends nothing', async () => {
        const result = await runHog(['feedback', 'hog is slow to start', '--dry-run'], {
            ...ON,
            env: AGENT,
            respond: () => ({ status: 200, body: {} }),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ sent: false, dryRun: true })
        expect(feedbackEvents(result)).toEqual([])
    })
})
