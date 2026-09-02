import * as fs from 'fs'
import * as path from 'path'
import { parse as parseYaml } from 'yaml'

import { compileRecipe, RecipeNormalizer } from '@posthog/llm-normalizer'

// The examples file is the DSL reference embedded in the create_ai_trace_parser tool prompt;
// running every documented example against the real compiler keeps the prompt from drifting.
// The test lives next to the yaml (not in the normalizer package) because the prompt is
// owned by this product's backend.
const EXAMPLES_PATH = path.resolve(__dirname, '../backend/prompts/parser_recipe_examples.yaml')

interface ExampleCase {
    input: unknown
    default_role?: string
    expect: unknown[]
}

interface Example {
    title: string
    teaches?: string
    recipe: unknown
    cases: ExampleCase[]
}

describe('parser recipe DSL examples (prompt drift guard)', () => {
    const doc: { examples: Example[] } = parseYaml(fs.readFileSync(EXAMPLES_PATH, 'utf8'))

    it('documents at least one example with cases', () => {
        expect(doc.examples.length).toBeGreaterThan(0)
        for (const example of doc.examples) {
            expect(example.cases.length).toBeGreaterThan(0)
        }
    })

    doc.examples.forEach((example, exampleIndex) => {
        describe(example.title, () => {
            example.cases.forEach((exampleCase, index) => {
                it(`produces the documented messages (case ${index + 1})`, () => {
                    const recipe = compileRecipe(example.recipe, `example_${exampleIndex}`)
                    const normalizer = new RecipeNormalizer([recipe])

                    const outcome = normalizer.normalizeMessage(exampleCase.input, exampleCase.default_role ?? 'user')

                    expect(outcome.recognized).toBe(true)
                    expect(outcome.messages).toEqual(exampleCase.expect)
                })
            })
        })
    })
})
