import { cleanTagFilters, restoreTagFilters, saveTagFilters } from './resourceTagFilters'

describe('resource tag preferences', () => {
    beforeEach(() => localStorage.clear())

    it('keeps each resource, project, and user independent', () => {
        const selection = { tags: ['quality', 'production'], tag_match: 'all' as const }
        saveTagFilters('scorers', selection, 1, 10)
        expect(restoreTagFilters('scorers', {}, 1, 10)).toEqual(selection)
        expect(restoreTagFilters('datasets', {}, 1, 10).tags).toEqual([])
        expect(restoreTagFilters('experiments', {}, 1, 10).tags).toEqual([])
        expect(restoreTagFilters('scorers', {}, 2, 10).tags).toEqual([])
        expect(restoreTagFilters('scorers', {}, 1, 11).tags).toEqual([])
    })

    it('gives shared URLs precedence, including an explicitly empty filter', () => {
        saveTagFilters('datasets', { tags: ['saved'], tag_match: 'all' }, 1, 10)
        expect(restoreTagFilters('datasets', { tags: ['shared'], tag_match: 'any' }, 1, 10)).toEqual({
            tags: ['shared'],
            tag_match: 'any',
        })
        expect(restoreTagFilters('datasets', { tags: [] }, 1, 10)).toEqual({ tags: [], tag_match: 'any' })
        expect(restoreTagFilters('datasets', { tags: 'broken' }, 1, 10).tags).toEqual([])
    })

    it('preserves commas and normalizes names when decoding a URL', () => {
        expect(cleanTagFilters({ tags: '[" Quality ", "QUALITY", "a,b"]', tag_match: 'all' })).toEqual({
            tags: ['quality', 'a,b'],
            tag_match: 'all',
        })
    })

    it('can clear a saved selection', () => {
        saveTagFilters('experiments', { tags: ['quality'], tag_match: 'all' }, 1, 10)
        saveTagFilters('experiments', { tags: [], tag_match: 'any' }, 1, 10)
        expect(restoreTagFilters('experiments', {}, 1, 10).tags).toEqual([])
    })
})
