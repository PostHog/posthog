import { loadRecipes } from './registry'

describe('loadRecipes', () => {
    it('loads the bundled recipes', () => {
        const recipes = loadRecipes()
        expect(recipes.length).toBeGreaterThan(0)
        expect(recipes.every((r) => typeof r.id === 'string' && r.id.length > 0)).toBe(true)
    })

    it('every loaded recipe has a unique priority', () => {
        const priorities = loadRecipes().map((r) => r.priority)
        expect(new Set(priorities).size).toBe(priorities.length)
    })
})
