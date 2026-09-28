import jwt from 'jsonwebtoken'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { createExampleInvocation } from '../_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '../async-function-registry'
import { MinimalLogEntry } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import './classify'

describe('postHogClassify', () => {
    const payload = {
        question: 'Is this ticket spam?',
        context: { subject: 'Buy SEO' },
        categories: { spam: 'Cold outreach', support: 'A customer asking for help' },
    }

    const invokeLive = async (args: Record<string, unknown>): Promise<void> => {
        const invocation = { ...createExampleInvocation(), hogFlow: { id: 'flow-1' } }
        await getAsyncFunctionHandler('postHogClassify')!.execute(
            [args],
            {
                invocation,
                internalApiBaseUrl: defaultConfig.INTERNAL_API_BASE_URL,
                consumeInlineAsyncBudget: () => {},
            } as unknown as AsyncFunctionContext,
            createInvocationResult<typeof invocation>(invocation)
        )
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
        // The literal pins the dev default shared with Django's WORKFLOW_CLASSIFY_JWT_SECRETS.
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(
            options.headers.Authorization.replace('Bearer ', ''),
            'local-dev-workflow-classify-jwt',
            {
                audience: 'posthog:workflows:classify',
                algorithms: ['HS256'],
            }
        ) as jwt.JwtPayload
        expect(claims).toMatchObject({ team_id: 1, hog_flow_id: 'flow-1' })
    })

    it.each([
        ['a blank question', { ...payload, question: ' ' }, /Enter a question/],
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
    ])('rejects %s in both mocked and live calls', async (_name, args, expected) => {
        expect(() => getAsyncFunctionHandler('postHogClassify')!.mock([args], [] as MinimalLogEntry[])).toThrow(
            expected
        )
        await expect(invokeLive(args)).rejects.toThrow(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
