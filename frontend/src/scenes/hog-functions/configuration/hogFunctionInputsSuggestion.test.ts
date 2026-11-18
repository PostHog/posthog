import { CyclotronJobInputSchemaType } from '~/types'

import { hogFunctionInputsSuggestion } from './hogFunctionInputsSuggestion'

const SLACK_SCHEMA: CyclotronJobInputSchemaType[] = [{ key: 'blocks', type: 'json', label: 'Blocks' }]

describe('hogFunctionInputsSuggestion', () => {
    it('keeps the current input settings and swaps in the proposed value', () => {
        const suggestion = hogFunctionInputsSuggestion(
            { inputs_schema: SLACK_SCHEMA, inputs: { blocks: [{ type: 'divider' }] } },
            { blocks: { value: [{ type: 'section' }], templating: 'liquid' } },
            SLACK_SCHEMA
        )
        expect(suggestion).toEqual({
            inputsSchema: SLACK_SCHEMA,
            inputValues: { blocks: { value: [{ type: 'divider' }], templating: 'liquid' } },
        })
    })

    it('reads the bare schema list that a backend without input values returns', () => {
        expect(hogFunctionInputsSuggestion(SLACK_SCHEMA, {}, SLACK_SCHEMA)).toEqual({
            inputsSchema: SLACK_SCHEMA,
            inputValues: {},
        })
    })

    it('holds the current value of every input whose type the suggestion changes', () => {
        const currentSchema: CyclotronJobInputSchemaType[] = [
            ...SLACK_SCHEMA,
            { key: 'footer', type: 'string', label: 'Footer' },
        ]
        const retypedSchema: CyclotronJobInputSchemaType[] = [
            { key: 'blocks', type: 'string', label: 'Blocks' },
            { key: 'footer', type: 'json', label: 'Footer' },
        ]
        const currentInputs = { blocks: { value: [{ type: 'section' }] } }

        expect(
            hogFunctionInputsSuggestion({ inputs_schema: retypedSchema, inputs: {} }, currentInputs, currentSchema)
        ).toEqual({
            inputsSchema: retypedSchema,
            inputValues: { blocks: { value: [{ type: 'section' }] }, footer: { value: null } },
        })
    })
})
