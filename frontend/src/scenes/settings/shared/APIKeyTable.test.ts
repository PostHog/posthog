import { formatCreatedBy } from './APIKeyTable'

describe('formatCreatedBy', () => {
    it.each([
        [{ email: 'jane@example.com', first_name: 'Jane', last_name: 'doe' }, 'Jane D.'],
        [{ email: 'jane@example.com', first_name: 'Jane', last_name: '' }, 'Jane'],
        [{ email: 'jane@example.com', first_name: 'Jane' }, 'Jane'],
        [{ email: 'jane@example.com', first_name: '', last_name: 'Doe' }, 'jane@example.com'],
        [{ email: 'jane@example.com' }, 'jane@example.com'],
    ])('formats %j as %s', (user, expected) => {
        expect(formatCreatedBy(user)).toEqual(expected)
    })
})
