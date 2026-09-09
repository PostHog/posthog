import { getAsyncFunctionHandler } from '../async-function-registry'
import { MinimalLogEntry } from '../types'
import './create-customer-task'

describe('postHogCreateCustomerTask', () => {
    const invokeMock = (payload: Record<string, unknown>): any =>
        getAsyncFunctionHandler('postHogCreateCustomerTask')!.mock([payload], [] as MinimalLogEntry[])

    // The step test panel mocks async functions by default. A mock body carrying fields the
    // endpoint never returns lets an author map an output that resolves to nothing live.
    it('answers with only the field the endpoint returns', () => {
        expect(invokeMock({ name: 'Follow up', description: 'Review the account', assigned_to_id: 42 })).toEqual({
            status: 201,
            body: { id: '00000000-0000-4000-8000-000000000000' },
        })
    })

    it.each([
        ['a blank name', { name: '   ' }, /Enter a task name/],
        ['a fractional assignee', { name: 'Follow up', assigned_to_id: 1.5 }, /valid numeric assignee user ID/],
        ['a non-numeric assignee', { name: 'Follow up', assigned_to_id: 'someone' }, /valid numeric assignee user ID/],
    ])('rejects %s in a mocked test, the way the live call does', (_name, payload, expected) => {
        expect(() => invokeMock(payload)).toThrow(expected)
    })
})
