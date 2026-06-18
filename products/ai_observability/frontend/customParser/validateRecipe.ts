import { parse as parseYaml } from 'yaml'

import { compileRecipe, mergeRecipes, RecipeNormalizer, RunOutcome, StoredRecipe } from '../normalizer'

export interface RecipeValidationSample {
    input: unknown
    output: unknown
    tools?: unknown
    inputRecognized: boolean
    outputRecognized: boolean
}

export interface RecipeVerdict {
    valid: boolean
    error?: string
}

// Validates a candidate recipe the way production runs it: real compiler, merged after the
// built-ins and team recipes, executed against the actual sample event. Valid means every
// previously-unrecognized side is now recognized.
export function validateRecipeAgainstSample(
    source: string,
    existingRecipes: StoredRecipe[],
    sample: RecipeValidationSample
): RecipeVerdict {
    let parsed: unknown
    try {
        parsed = parseYaml(source)
    } catch (error) {
        return { valid: false, error: `the recipe is not valid YAML: ${errorMessage(error)}` }
    }
    try {
        compileRecipe(parsed, '__candidate__')
    } catch (error) {
        return { valid: false, error: `the recipe does not compile: ${errorMessage(error)}` }
    }

    let inputOutcome: RunOutcome
    let outputOutcome: RunOutcome
    try {
        const normalizer = new RecipeNormalizer(mergeRecipes([...existingRecipes, { id: '__candidate__', source }]))
        inputOutcome = normalizer.normalizeMessages(sample.input, 'user', sample.tools)
        outputOutcome = normalizer.normalizeMessages(sample.output, 'assistant')
    } catch (error) {
        // E.g. self-delegation: compiles, but trips the depth guard at runtime — a fixable recipe bug
        return { valid: false, error: `the recipe failed while running against the sample: ${errorMessage(error)}` }
    }

    const stillUnrecognized = [
        !sample.inputRecognized && !inputOutcome.recognized ? 'input' : null,
        !sample.outputRecognized && !outputOutcome.recognized ? 'output' : null,
    ].filter((side): side is string => side !== null)

    if (stillUnrecognized.length > 0) {
        return {
            valid: false,
            error:
                `no rule matched the sample ${stillUnrecognized.join(' or ')} — ` +
                'the event still falls back to raw JSON. Write rules that match the shapes in the sample.',
        }
    }
    return { valid: true }
}

export interface CreateParserRecipeHandlerDeps {
    /** UUID of the event this handler validates against */
    eventId: string
    existingRecipes: StoredRecipe[]
    sample: RecipeValidationSample
    /** Persists the recipe and returns its id */
    saveRecipe: (name: string, source: string) => Promise<string>
}

// The create_ai_trace_parser client execution handler; the verdict shape is the contract with
// the backend tool's ParserRecipeVerdict model.
export async function handleCreateParserRecipeCall(
    args: Record<string, any>,
    deps: CreateParserRecipeHandlerDeps
): Promise<Record<string, unknown>> {
    // The registration follows the selected event — refuse rather than validate a recipe
    // written for a different event against the wrong sample
    if (typeof args.event_uuid === 'string' && args.event_uuid && args.event_uuid !== deps.eventId) {
        return {
            valid: false,
            wrong_event: true,
            error:
                'the user is now viewing a different event than the one this recipe was written for — ' +
                're-read the sample in your context and start over, or ask the user to reopen the original event',
        }
    }
    const name = typeof args.name === 'string' && args.name.trim() ? args.name.trim() : 'Custom parser'
    const source = typeof args.yaml_source === 'string' ? args.yaml_source : ''

    const verdict = validateRecipeAgainstSample(source, deps.existingRecipes, deps.sample)
    if (!verdict.valid) {
        return { valid: false, error: verdict.error }
    }
    // A retried call (e.g. after a failed resume turn) must not duplicate rows
    const alreadySaved = deps.existingRecipes.find((recipe) => recipe.source === source)
    if (alreadySaved) {
        return { valid: true, recipe_id: alreadySaved.id }
    }
    try {
        const recipeId = await deps.saveRecipe(name, source)
        return { valid: true, recipe_id: recipeId }
    } catch (error) {
        // Only persistence failed — the agent must not rewrite a correct recipe
        return { valid: true, saved: false, error: errorMessage(error) }
    }
}

function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
}
