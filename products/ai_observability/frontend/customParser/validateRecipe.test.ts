import { handleCreateParserRecipeCall, validateRecipeAgainstSample } from './validateRecipe'

const MATCHING_RECIPE = `
rules:
    - on:
          acme_kind: q
      emit:
          role: user
          content: $.acme_text
`

const NON_MATCHING_RECIPE = `
rules:
    - on:
          some_other_key: { exists: true }
      emit:
          role: user
          content: $.acme_text
`

const sample = {
    input: { acme_kind: 'q', acme_text: 'hello' },
    output: { acme_blob: { score: 1 } },
    inputRecognized: false,
    outputRecognized: true,
}

describe('custom parser validation', () => {
    describe('validateRecipeAgainstSample', () => {
        it('rejects source that is not valid YAML', () => {
            const verdict = validateRecipeAgainstSample('rules: [unclosed', [], sample)

            expect(verdict.valid).toBe(false)
            expect(verdict.error).toContain('not valid YAML')
        })

        it('rejects source that does not compile', () => {
            const verdict = validateRecipeAgainstSample(
                'rules:\n    - on:\n          a: 1\n      emit:\n          content: { selectt: { from: $.x } }\n',
                [],
                sample
            )

            expect(verdict.valid).toBe(false)
            expect(verdict.error).toContain('does not compile')
        })

        it('rejects a recipe that leaves the unrecognized side unrecognized', () => {
            const verdict = validateRecipeAgainstSample(NON_MATCHING_RECIPE, [], sample)

            expect(verdict.valid).toBe(false)
            expect(verdict.error).toContain('no rule matched the sample input')
        })

        it('accepts a recipe that makes the unrecognized side recognized', () => {
            const verdict = validateRecipeAgainstSample(MATCHING_RECIPE, [], sample)

            expect(verdict).toEqual({ valid: true })
        })

        it('rejects a recipe that compiles but throws at runtime (self-delegation)', () => {
            const selfDelegating = 'rules:\n    - on:\n          acme_kind: q\n      delegate: $\n'

            const verdict = validateRecipeAgainstSample(selfDelegating, [], sample)

            expect(verdict.valid).toBe(false)
            expect(verdict.error).toContain('failed while running against the sample')
        })

        it('accepts a recipe whose rules match the elements of an array input', () => {
            // Top-level arrays are unwrapped by a built-in rule; elements re-match all recipes.
            const verdict = validateRecipeAgainstSample(MATCHING_RECIPE, [], {
                ...sample,
                input: [
                    { acme_kind: 'q', acme_text: 'first' },
                    { acme_kind: 'q', acme_text: 'second' },
                ],
            })

            expect(verdict).toEqual({ valid: true })
        })

        it('only requires the sides that were unrecognized to begin with', () => {
            // The output blob matches no rule, but it was already declared recognized.
            const verdict = validateRecipeAgainstSample(MATCHING_RECIPE, [], {
                ...sample,
                output: { acme_blob: { unparseable: true } },
            })

            expect(verdict).toEqual({ valid: true })
        })
    })

    describe('handleCreateParserRecipeCall', () => {
        const deps = {
            eventId: 'event-1',
            existingRecipes: [] as { id: string; source: string }[],
            sample,
            saveRecipe: jest.fn(),
        }
        const args = { name: 'Acme SDK', yaml_source: MATCHING_RECIPE, event_uuid: 'event-1' }

        beforeEach(() => {
            deps.existingRecipes = []
            deps.saveRecipe.mockReset()
            deps.saveRecipe.mockResolvedValue('recipe-1')
        })

        it('validates and saves, returning the recipe id', async () => {
            const result = await handleCreateParserRecipeCall(args, deps)

            expect(result).toEqual({ valid: true, recipe_id: 'recipe-1' })
            expect(deps.saveRecipe).toHaveBeenCalledWith('Acme SDK', MATCHING_RECIPE)
        })

        it('refuses when the recipe was written for a different event', async () => {
            const result = await handleCreateParserRecipeCall({ ...args, event_uuid: 'event-2' }, deps)

            expect(result.valid).toBe(false)
            expect(result.wrong_event).toBe(true)
            expect(result.error).toContain('different event')
            expect(deps.saveRecipe).not.toHaveBeenCalled()
        })

        it('reports a save failure as valid-but-unsaved so the agent does not rewrite', async () => {
            deps.saveRecipe.mockRejectedValue(new Error('500 from API'))

            const result = await handleCreateParserRecipeCall(args, deps)

            expect(result).toEqual({ valid: true, saved: false, error: '500 from API' })
        })

        it('reuses an existing identical recipe instead of saving a duplicate', async () => {
            deps.existingRecipes = [{ id: 'recipe-0', source: MATCHING_RECIPE }]

            const result = await handleCreateParserRecipeCall(args, deps)

            expect(result).toEqual({ valid: true, recipe_id: 'recipe-0' })
            expect(deps.saveRecipe).not.toHaveBeenCalled()
        })

        it('passes validation failures through unchanged', async () => {
            const result = await handleCreateParserRecipeCall({ ...args, yaml_source: NON_MATCHING_RECIPE }, deps)

            expect(result.valid).toBe(false)
            expect(result.error).toContain('no rule matched')
            expect(deps.saveRecipe).not.toHaveBeenCalled()
        })
    })
})
