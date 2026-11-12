import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-http-request.template'

describe('posthog http request template', () => {
    const tester = new TemplateTester(template)
    const url = 'https://example.com/health'

    beforeEach(async () => {
        await tester.beforeEach()
    })

    afterEach(() => tester.afterEach())

    const run = async (
        inputs: Record<string, any>,
        response: { status: number; body: unknown; duration_ms: number; error?: string }
    ) => {
        const first = await tester.invoke({ url, ...inputs })
        first.invocation.state.vmState!.stack.push(response)
        return { first, result: await tester.resumeInvocation(first.invocation) }
    }

    it('makes one attempt that does not fail the step', async () => {
        const { first } = await run(
            { method: 'post', headers: { 'X-Check': '1' }, body: { ping: true }, timeout_ms: 2500 },
            { status: 200, body: 'ok', duration_ms: 1 }
        )

        expect(first.invocation.queueParameters).toEqual({
            type: 'fetch',
            url,
            method: 'POST',
            headers: { 'X-Check': '1' },
            body: '{"ping":true}',
            timeout_ms: 2500,
            max_tries: 1,
            fail_on_error: false,
        })
    })

    it.each([
        ['a 2xx', {}, { status: 200, body: 'ok' }, { ok: true, status: 200, error: null, body: 'ok' }],
        [
            'a 5xx',
            {},
            { status: 503, body: 'down' },
            { ok: false, status: 503, error: 'Expected status 2xx,3xx but got 503', body: 'down' },
        ],
        [
            'an exact code from a list',
            { expected_status: '200, 204' },
            { status: 204, body: '' },
            { ok: true, status: 204, error: null },
        ],
        [
            'a code outside the list',
            { expected_status: '200' },
            { status: 301, body: '' },
            { ok: false, status: 301, error: 'Expected status 200 but got 301' },
        ],
        [
            'a JSON body that contains the text',
            { body_contains: '"healthy"' },
            { status: 200, body: { status: 'healthy' } },
            { ok: true, error: null, body: '{"status":"healthy"}' },
        ],
        [
            'a body without the text',
            { body_contains: 'healthy' },
            { status: 200, body: 'degraded' },
            { ok: false, error: 'The response body does not contain "healthy"' },
        ],
        [
            'no response',
            {},
            { status: 500, body: 'TypeError: fetch failed', error: 'TypeError: fetch failed' },
            { ok: false, status: 0, error: 'TypeError: fetch failed', body: '' },
        ],
    ])('reports %s', async (_name, inputs, response, expected) => {
        const { result } = await run(inputs, { ...response, duration_ms: 42 })

        expect(result.error).toBeUndefined()
        expect(result.finished).toBe(true)
        expect(result.execResult).toMatchObject({ ...expected, duration_ms: 42 })
    })

    it('clips a long body', async () => {
        const { result } = await run({}, { status: 200, body: 'a'.repeat(5000), duration_ms: 1 })

        expect((result.execResult as { body: string }).body).toHaveLength(1000)
    })
})
