import { toTicketAssignee, isSameAssigneeEntry } from './types'

describe('assignee filter entries', () => {
    describe('toTicketAssignee', () => {
        it.each([
            ['user', { type: 'user' as const, id: 3, user: { email: 'test@example.com' } }, { type: 'user', id: 3 }],
            [
                'role',
                { type: 'role' as const, id: 'role-1', role: { members: [1, 2] } },
                { type: 'role', id: 'role-1' },
            ],
        ])('keeps only the %s identity', (_name, assignee, expected) => {
            expect(toTicketAssignee(assignee)).toEqual(expected)
        })
    })

    describe('isSameAssigneeEntry', () => {
        it.each([
            ['matches the me token to itself', 'me' as const, 'me' as const, true],
            ['does not match me to unassigned', 'me' as const, 'unassigned' as const, false],
            ['does not match me to a concrete user', 'me' as const, { type: 'user' as const, id: 1 }, false],
            [
                'matches a user id across number and string',
                { type: 'user' as const, id: 1 },
                { type: 'user' as const, id: '1' },
                true,
            ],
            [
                'does not match a user to a role with the same id',
                { type: 'user' as const, id: 1 },
                { type: 'role' as const, id: '1' },
                false,
            ],
        ])('%s', (_name, left, right, expected) => {
            expect(isSameAssigneeEntry(left, right)).toBe(expected)
        })
    })
})
