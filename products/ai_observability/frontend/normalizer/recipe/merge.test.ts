import { mergeRecipes, StoredRecipe } from './merge'
import { loadRecipes } from './registry'

const ids = (recipes: { id: string }[]): string[] => recipes.map((r) => r.id)
const builtinIds = (): string[] => ids(loadRecipes())

describe('mergeRecipes', () => {
    it('returns the bundled defaults in order when the team has no customs', () => {
        expect(ids(mergeRecipes([]))).toEqual(builtinIds())
    })

    it('identifies customs by their database id, not any id in the source, and runs them last', () => {
        const customs: StoredRecipe[] = [
            { id: 'db-first', source: 'rules: []\n' },
            { id: 'db-second', source: 'id: ignored\nrules: []\n' },
        ]
        const merged = ids(mergeRecipes(customs))
        expect(merged.slice(-2)).toEqual(['db-first', 'db-second'])
    })

    it('keeps every builtin present alongside the customs', () => {
        const merged = ids(mergeRecipes([{ id: 'db-custom', source: 'rules: []\n' }]))
        for (const builtin of builtinIds()) {
            expect(merged).toContain(builtin)
        }
        expect(merged).toContain('db-custom')
        expect(loadRecipes().find((r) => r.id === 'openai_chat')!.rules.length).toBeGreaterThan(0)
    })

    it('skips a custom recipe that fails to compile', () => {
        const broken: StoredRecipe = { id: 'db-custom', source: 'not: [valid' }
        expect(ids(mergeRecipes([broken]))).toEqual(builtinIds())
    })
})
