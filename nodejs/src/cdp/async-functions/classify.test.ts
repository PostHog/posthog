import { defaultConfig } from '~/common/config/config'
import { StallingValkeyProxy } from '~/common/redis/_tests/stalling-valkey-proxy'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'

import { createExampleInvocation } from '../_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '../async-function-registry'
import { MinimalLogEntry } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { ClassifyDailyCap } from './classify'

describe('postHogClassify', () => {
    const payload = {
        question: 'Is this ticket spam?',
        context: { subject: 'Buy SEO' },
        categories: { spam: 'Cold outreach', support: 'A customer asking for help' },
    }

    const enqueue = async (args: Record<string, unknown>): Promise<void> => {
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
    ])('rejects %s in both mocked and queued calls', async (_name, args, expected) => {
        expect(() => getAsyncFunctionHandler('postHogClassify')!.mock([args], [] as MinimalLogEntry[])).toThrow(
            expected
        )
        await expect(enqueue(args)).rejects.toThrow(expected)
    })

    describe('daily cap', () => {
        let store: StallingValkeyProxy

        beforeEach(() => {
            store = new StallingValkeyProxy({ host: defaultConfig.CDP_REDIS_HOST, port: defaultConfig.CDP_REDIS_PORT })
        })

        afterEach(() => {
            store.stop()
        })

        it('lets a classification through when Valkey stops answering', async () => {
            const port = await store.start()
            const cap = new ClassifyDailyCap(
                createRedisV2PoolFromConfig({
                    connection: {
                        url: '127.0.0.1',
                        options: { port, password: defaultConfig.CDP_REDIS_PASSWORD, retryStrategy: () => null },
                        name: 'classify-daily-cap-stalling',
                        exitOnRepeatedErrors: false,
                    },
                    poolMinSize: 0,
                    poolMaxSize: 1,
                }),
                1
            )
            store.stopAnswering()

            let gaveUp: NodeJS.Timeout | undefined
            const answer = await Promise.race([
                cap.countAndCheck(1),
                new Promise<'no answer'>((resolve) => {
                    gaveUp = setTimeout(() => resolve('no answer'), 10_000)
                }),
            ]).finally(() => clearTimeout(gaveUp))

            expect(answer).toBe(true)
        })
    })
})
