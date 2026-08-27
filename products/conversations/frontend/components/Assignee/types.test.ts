import { toTicketAssignee } from './types'

describe('toTicketAssignee', () => {
    it.each([
        ['user', { type: 'user' as const, id: 3, user: { email: 'test@example.com' } }, { type: 'user', id: 3 }],
        ['role', { type: 'role' as const, id: 'role-1', role: { members: [1, 2] } }, { type: 'role', id: 'role-1' }],
    ])('keeps only the %s identity', (_name, assignee, expected) => {
        expect(toTicketAssignee(assignee)).toEqual(expected)
    })
})
