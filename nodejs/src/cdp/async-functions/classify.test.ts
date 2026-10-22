import jwt from 'jsonwebtoken'

import { VMState } from '@posthog/hogvm'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { createExampleInvocation } from '../_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, MinimalLogEntry } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import './classify'

describe('postHogClassify', () => {
    const payload = {
        question: 'Is this ticket spam?',
        context: { subject: 'Buy SEO' },
        categories: { spam: 'Cold outreach', support: 'A customer asking for help' },
    }

    const invokeLive = async (
        args: Record<string, unknown>,
        { attempts = 0, isTest = false } = {}
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> => {
        const example = createExampleInvocation()
        const invocation = {
            ...example,
            state: { ...example.state, attempts, vmState: { stack: [] } as unknown as VMState },
            hogFlow: { id: 'flow-1' },
        }
        const result = createInvocationResult<typeof invocation>(invocation)
        await getAsyncFunctionHandler('postHogClassify')!.execute(
            [args],
            {
                invocation,
                internalApiBaseUrl: defaultConfig.INTERNAL_API_BASE_URL,
                consumeInlineAsyncBudget: () => {},
                isTest,
            } as unknown as AsyncFunctionContext,
            result
        )
        return result
    }

    let fetchSpy: jest.SpyInstance
    beforeEach(() => {
        fetchSpy = jest.spyOn(requestModule, 'internalFetch').mockResolvedValue({
            status: 200,
            text: () => Promise.resolve(JSON.stringify({ category: 'spam', confidence: 0.9 })),
        } as requestModule.FetchResponse)
    })
    afterEach(() => jest.restoreAllMocks())

    it('posts the inputs with a token scoped to the workflow', async () => {
        await invokeLive(payload)

        const [url, options] = fetchSpy.mock.calls[0]
        expect(url).toMatch(/\/api\/projects\/1\/workflow_classifications\/$/)
        expect(parseJSON(options.body)).toEqual(payload)
        // Must exceed Django's 5 second gateway timeout so the worker receives its 503 instead of aborting first.
        expect(options.timeoutMs).toBeGreaterThan(5000)
        const token = options.headers.Authorization.replace('Bearer ', '')
        // The literal pins the dev default shared with Django's WORKFLOW_CLASSIFY_JWT_SECRETS.
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(token, 'local-dev-workflow-classify-jwt', {
            audience: 'posthog:workflows:classify',
            algorithms: ['HS256'],
        }) as jwt.JwtPayload
        expect(claims).toMatchObject({ team_id: 1, hog_flow_id: 'flow-1' })
    })

    it.each([
        ['a timeout, which may still be answering', new DOMException('The operation timed out.', 'TimeoutError'), 1],
        ['a refused connection, which never reached Django', new Error('connect ECONNREFUSED 127.0.0.1:8000'), 3],
    ])('retries after %s only when no answer can still arrive', async (_name, error, expectedCalls) => {
        jest.useFakeTimers()
        try {
            fetchSpy.mockRejectedValue(error)
            const invoked = invokeLive(payload)
            await jest.runAllTimersAsync()
            await invoked

            expect(fetchSpy).toHaveBeenCalledTimes(expectedCalls)
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        ['the first busy answer', 0, false, true],
        ['the last busy answer', 3, false, false],
        ['a test run', 0, true, false],
    ])(
        'on %s, asks once and schedules a later retry only while retries remain',
        async (_name, attempts, isTest, scheduled) => {
            fetchSpy.mockResolvedValue({
                status: 503,
                text: () =>
                    Promise.resolve(JSON.stringify({ detail: 'The model is busy or unreachable. Retry later.' })),
            } as requestModule.FetchResponse)

            const result = await invokeLive(payload, { attempts, isTest })

            // An immediate retry would add load to a busy gateway and hold the consumer loop.
            expect(fetchSpy).toHaveBeenCalledTimes(1)
            expect(result.invocation.state.vmState!.stack).toEqual([
                { status: 503, body: expect.anything(), retry_scheduled: scheduled || undefined },
            ])
            expect(Boolean(result.invocation.queueScheduledAt)).toBe(scheduled)
            expect(result.invocation.state.attempts).toBe(scheduled ? attempts + 1 : 0)
        }
    )

    it.each([
        ['a blank question', { ...payload, question: ' ' }, /Enter a question/],
        ['a long question', { ...payload, question: 'x'.repeat(2001) }, /2000 characters or fewer/],
        [
            'a blank category name',
            { ...payload, categories: { ' ': 'Spam', support: 'Help' } },
            /Give every category a name/,
        ],
        [
            'a long category name',
            { ...payload, categories: { ['x'.repeat(101)]: 'Spam', support: 'Help' } },
            /category names to 100 characters or fewer/,
        ],
        ['one category', { ...payload, categories: { spam: 'Spam' } }, /at least two categories/],
        [
            'seventeen categories',
            { ...payload, categories: Object.fromEntries(Array.from({ length: 17 }, (_, i) => [`c${i}`, 'x'])) },
            /at most 16 categories/,
        ],
        [
            'a long category description',
            { ...payload, categories: { spam: 'x'.repeat(501), support: 'Help' } },
            /500 characters or fewer/,
        ],
        ['an oversized context', { ...payload, context: { message: 'x'.repeat(65_536) } }, /65536 characters of JSON/],
        [
            'a deeply nested context',
            { ...payload, context: Array.from({ length: 255 }).reduce<unknown>((inner) => ({ a: inner }), 'x') },
            /100 levels of nesting or fewer/,
        ],
    ])('rejects %s in both mocked and live calls', async (_name, args, expected) => {
        expect(() => getAsyncFunctionHandler('postHogClassify')!.mock([args], [] as MinimalLogEntry[])).toThrow(
            expected
        )
        await expect(invokeLive(args)).rejects.toThrow(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
