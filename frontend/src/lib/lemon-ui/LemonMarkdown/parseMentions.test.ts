import { OrganizationMemberType } from '~/types'
import { findMentionMatch, parseMentions } from './parseMentions'

const mockMembers: OrganizationMemberType[] = [
    {
        user: { id: 1, first_name: 'Alice', last_name: 'Smith', email: 'alice@example.com' },
        level: 1,
        joined_at: '2023-01-01',
        updated_at: '2023-01-01',
    },
    {
        user: { id: 2, first_name: 'Bob', last_name: 'Johnson', email: 'bob@example.com' },
        level: 1,
        joined_at: '2023-01-02',
        updated_at: '2023-01-02',
    },
    {
        user: { id: 3, first_name: 'Charlie', last_name: 'Brown', email: 'charlie@example.com' },
        level: 1,
        joined_at: '2023-01-03',
        updated_at: '2023-01-03',
    },
    {
        user: { id: 4, first_name: 'Al', last_name: 'Green', email: 'al@example.com' },
        level: 1,
        joined_at: '2023-01-04',
        updated_at: '2023-01-04',
    },
] as OrganizationMemberType[]

describe('parseMentions', () => {
    it.each([
        ['Hello world', [{ type: 'text', content: 'Hello world' }]],
        [
            'Hello @Alice',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' },
            ],
        ],
        [
            'Hello @Alice how are you?',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' },
                { type: 'text', content: ' how are you?' },
            ],
        ],
        [
            'Hello @Alice and @Bob',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' },
                { type: 'text', content: ' and ' },
                { type: 'mention', content: 'Bob', userId: 2, originalText: '@Bob' },
            ],
        ],
        [
            '@Alice hello',
            [
                { type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' },
                { type: 'text', content: ' hello' },
            ],
        ],
        ['@Alice', [{ type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' }]],
        [
            'Hello @alice',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' },
            ],
        ],
        [
            'Hello @Al',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'mention', content: 'Al', userId: 4, originalText: '@Al' },
            ],
        ],
        [
            'Hey @Alice, can you help @Bob with the task? Thanks!',
            [
                { type: 'text', content: 'Hey ' },
                { type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' },
                { type: 'text', content: ', can you help ' },
                { type: 'mention', content: 'Bob', userId: 2, originalText: '@Bob' },
                { type: 'text', content: ' with the task? Thanks!' },
            ],
        ],
    ])('parses "%s"', (input, expected) => {
        expect(parseMentions(input, mockMembers)).toEqual(expected)
    })

    it.each([
        [
            'Hello @David',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'text', content: '@' },
                { type: 'text', content: 'David' },
            ],
        ],
        [
            'Hello @',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'text', content: '@' },
            ],
        ],
        [
            'Hello @@Alice',
            [
                { type: 'text', content: 'Hello ' },
                { type: 'text', content: '@' },
                { type: 'mention', content: 'Alice', userId: 1, originalText: '@Alice' },
            ],
        ],
        [
            '@@@',
            [
                { type: 'text', content: '@' },
                { type: 'text', content: '@' },
                { type: 'text', content: '@' },
            ],
        ],

        [
            '@ @  @   ',
            [
                {
                    content: '@',
                    type: 'text',
                },
                {
                    content: ' ',
                    type: 'text',
                },
                {
                    content: '@',
                    type: 'text',
                },
                {
                    content: '  ',
                    type: 'text',
                },
                {
                    content: '@',
                    type: 'text',
                },
                {
                    content: '   ',
                    type: 'text',
                },
            ],
        ],

        ['', []],
    ])('handles invalid mentions in "%s"', (input, expected) => {
        expect(parseMentions(input, mockMembers)).toEqual(expected)
    })

    describe('findMentionMatch', () => {
        it.each([
            ['Alice', { displayName: 'Alice', userId: 1, length: 5 }],
            ['alice', { displayName: 'Alice', userId: 1, length: 5 }],
            ['Alice how are you?', { displayName: 'Alice', userId: 1, length: 5 }],
            ['Al', { displayName: 'Al', userId: 4, length: 2 }],
            ['Alic', { displayName: 'Al', userId: 4, length: 2 }],
        ])('finds match for "%s"', (input, expected) => {
            const result = findMentionMatch(input, mockMembers)

            expect(result).not.toBeNull()
            expect(result?.displayName).toBe(expected.displayName)
            expect(result?.member.user.id).toBe(expected.userId)
            expect(result?.length).toBe(expected.length)
        })

        it.each([['David'], ['']])('returns null for "%s"', (input) => {
            expect(findMentionMatch(input, mockMembers)).toBeNull()
        })
    })
})
