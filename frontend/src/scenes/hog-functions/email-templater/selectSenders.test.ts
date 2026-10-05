import { selectSenders } from './selectSenders'

describe('selectSenders', () => {
    const current = { integrationId: 1, email: 'custom@example.com', name: 'Custom' }

    it.each([
        {
            case: 'picking the sandbox sender keeps only it and drops the custom sender values',
            ids: [1, 2, 7],
            sandboxId: 7,
            expected: { integrationId: 7, integrationIds: undefined, email: undefined, name: undefined },
        },
        {
            case: 'adding an own sender while the sandbox sender is selected drops the sandbox sender',
            value: { integrationId: 7 },
            ids: [7, 1],
            sandboxId: 7,
            expected: { integrationId: 1, integrationIds: undefined },
        },
        {
            case: 'own senders rotate and keep the custom sender values',
            ids: [1, 2],
            sandboxId: 7,
            expected: { integrationId: 1, integrationIds: [1, 2], email: 'custom@example.com', name: 'Custom' },
        },
        {
            case: 'picking the sandbox sender over a full rotation still works',
            ids: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 7],
            sandboxId: 7,
            expected: { integrationId: 7, integrationIds: undefined },
        },
        {
            case: 'a surface without the sandbox sender treats its id like any other',
            ids: [1, 7],
            sandboxId: undefined,
            expected: { integrationId: 1, integrationIds: [1, 7] },
        },
        {
            case: 'more senders than the limit are refused',
            ids: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12],
            sandboxId: 7,
            expected: null,
        },
    ])('$case', ({ value = current, ids, sandboxId, expected }) => {
        expect(selectSenders(value, ids, sandboxId)).toEqual(
            expected === null ? null : expect.objectContaining(expected)
        )
    })
})
