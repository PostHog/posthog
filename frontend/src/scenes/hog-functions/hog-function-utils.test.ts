import { CyclotronJobInputSchemaType } from '~/types'

import { getHogFunctionDeliveryType, legacyPluginTemplateId, redactSecretHogFunctionInputs } from './hog-function-utils'

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

// The destinations list drops a plugin config whose template a migrated legacy_destination already
// carries, so this id has to match the one the migration writes.
describe('legacyPluginTemplateId', () => {
    it.each([
        ['https://github.com/PostHog/customerio-plugin', 'plugin-customerio-plugin'],
        ['inline://semver-flattener', 'plugin-semver-flattener-plugin'],
        ['inline://user-agent', 'plugin-user-agent-plugin'],
        [undefined, undefined],
    ])('maps %s to %s', (url, expected) => {
        expect(legacyPluginTemplateId(url)).toBe(expected)
    })
})
