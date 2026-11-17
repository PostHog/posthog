import { CyclotronJobInputSchemaType } from '~/types'

import {
    getHogFunctionDeliveryType,
    hogFunctionInputsSuggestion,
    redactSecretHogFunctionInputs,
} from './hog-function-utils'

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

// The diff-builder test covers schema-marked secrets end to end; this covers the entry-marked branch
// (a saved secret carries `secret: true` on the input entry itself, with no schema flag needed).
describe('redactSecretHogFunctionInputs', () => {
    it('redacts entry-marked secrets and leaves plain inputs untouched', () => {
        const redacted = redactSecretHogFunctionInputs(
            {
                token: { value: 'tok-cleartext', secret: true },
                url: { value: 'https://example.com' },
            },
            [] as CyclotronJobInputSchemaType[]
        )
        expect(redacted.token.value).toBe('[secret]')
        expect(redacted.url.value).toBe('https://example.com')
    })
})

describe('getHogFunctionDeliveryType', () => {
    it.each([
        ['batch-export-9', 'batch'],
        ['batch-export-AwsS3', 'batch'],
        ['plugin-7', 'realtime'],
        ['abc123', 'realtime'],
        ['template-slack', 'realtime'],
    ])('classifies %s as %s', (id, expected) => {
        expect(getHogFunctionDeliveryType({ id })).toBe(expected)
    })
})
