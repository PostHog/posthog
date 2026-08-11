import { CyclotronJobInputSchemaType } from '~/types'

import { getHogFunctionDeliveryType, redactSecretHogFunctionInputs, validateAIFilters } from './hog-function-utils'

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

describe('validateAIFilters', () => {
    it('accepts a well-formed filters payload', () => {
        expect(
            validateAIFilters({
                events: [
                    {
                        id: '$pageview',
                        type: 'events',
                        properties: [{ key: '$browser', value: 'Chrome', operator: 'exact', type: 'event' }],
                    },
                ],
                properties: [{ key: 'email', value: ['a@example.com'], operator: 'exact', type: 'person' }],
            })
        ).toBeNull()
    })

    it.each([
        ['not an object', 'nope'],
        ['a top-level property with an unknown type', { properties: [{ key: 'x', type: 'bogus' }] }],
        ['a top-level property missing its type', { properties: [{ key: 'x' }] }],
        ['a nested property with an unknown type', { events: [{ id: '$pageview', properties: [{ type: 'bogus' }] }] }],
        ['events that is not a list', { events: { id: '$pageview' } }],
    ])('rejects %s', (_name, payload) => {
        expect(validateAIFilters(payload)).not.toBeNull()
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
