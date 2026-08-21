import { loadRecipes } from './registry'

describe('loadRecipes', () => {
    it('loads the bundled recipes', () => {
        const recipes = loadRecipes()
        expect(recipes.length).toBeGreaterThan(0)
        expect(recipes.every((r) => typeof r.id === 'string' && r.id.length > 0)).toBe(true)
    })

    it('has unique recipe ids', () => {
        const ids = loadRecipes().map((recipe) => recipe.id)
        expect(new Set(ids).size).toBe(ids.length)
    })
})
