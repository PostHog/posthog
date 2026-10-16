import { projectGroupTagFromName, uniqueProjectGroupNames } from './projectGroupTags'

describe('project group tags', () => {
    test.each([
        { name: 'production apps', expected: 'project-group:production-apps' },
        { name: 'HedgeBox', expected: 'project-group:hedgebox' },
        { name: '--staging---', expected: 'project-group:staging' },
        { name: '---', expected: null },
        { name: '   ', expected: null },
    ])('formats "$name" as a project group tag', ({ name, expected }) => {
        expect(projectGroupTagFromName(name)).toBe(expected)
    })

    test('returns sorted unique groups and skips ungrouped projects', () => {
        expect(uniqueProjectGroupNames(['staging', null, 'production', 'staging', undefined])).toEqual([
            'production',
            'staging',
        ])
    })
})
