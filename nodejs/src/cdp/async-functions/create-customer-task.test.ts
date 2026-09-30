import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { createExampleInvocation } from '../_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '../async-function-registry'
import { CyclotronJobInvocationHogFunctionContext, MinimalLogEntry } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import './create-customer-task'

describe('postHogCreateCustomerTask', () => {
    const invokeMock = (payload: Record<string, unknown>): any =>
        getAsyncFunctionHandler('postHogCreateCustomerTask')!.mock([payload], [] as MinimalLogEntry[])

    const invokeLive = async (
        payload: Record<string, unknown>,
        state: Partial<CyclotronJobInvocationHogFunctionContext> = {}
    ): Promise<void> => {
        const invocation = {
            ...createExampleInvocation(),
            hogFlow: { id: 'flow-1' },
        }
        Object.assign(invocation.state, { actionId: 'action_1', ...state })
        await getAsyncFunctionHandler('postHogCreateCustomerTask')!.execute(
            [payload],
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
            status: 201,
            text: () => Promise.resolve(JSON.stringify({ id: '00000000-0000-4000-8000-000000000000' })),
        } as requestModule.FetchResponse)
    })
    afterEach(() => jest.restoreAllMocks())

    // The step test panel mocks async functions by default. A mock body carrying fields the
    // endpoint never returns lets an author map an output that resolves to nothing live.
    it.each([42, null, undefined])('accepts assignee %j and returns only the task ID', (assigned_to_id) => {
        expect(invokeMock({ name: 'Follow up', description: 'Review the account', assigned_to_id })).toEqual({
            status: 201,
            body: { id: '00000000-0000-4000-8000-000000000000' },
        })
    })

    it.each([
        ['a blank name', { name: '   ' }, /Enter a task name/],
        ['a zero assignee', { name: 'Follow up', assigned_to_id: 0 }, /valid numeric assignee user ID/],
        ['a boolean assignee', { name: 'Follow up', assigned_to_id: true }, /valid numeric assignee user ID/],
        ['a fractional assignee', { name: 'Follow up', assigned_to_id: 1.5 }, /valid numeric assignee user ID/],
        ['a non-numeric assignee', { name: 'Follow up', assigned_to_id: 'someone' }, /valid numeric assignee user ID/],
    ])('rejects %s in both mocked and live calls', async (_name, payload, expected) => {
        expect(() => invokeMock(payload)).toThrow(expected)
        await expect(invokeLive(payload)).rejects.toThrow(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })

    it.each([null, undefined])('omits assignee %j from the live request', async (assigned_to_id) => {
        await invokeLive({ name: 'Follow up', assigned_to_id })

        expect(fetchSpy).toHaveBeenCalledTimes(1)
        const body = parseJSON(fetchSpy.mock.calls[0][1].body)
        expect(body.name).toBe('Follow up')
        expect(body).not.toHaveProperty('assigned_to_id')
    })

    it.each([undefined, -1, 1.5, NaN])('rejects invalid versioned visit count %j', async (actionStepCount) => {
        await expect(
            invokeLive({ name: 'Follow up' }, { customerTaskIdempotencyVersion: 1, actionStepCount })
        ).rejects.toThrow(/valid workflow visit count/)
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
