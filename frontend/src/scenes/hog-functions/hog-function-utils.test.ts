import { CyclotronJobInputSchemaType, HogFunctionType } from '~/types'

import {
    getHogFunctionDeliveryType,
    legacyPluginTemplateId,
    redactSecretHogFunctionInputs,
    withoutSupersededPluginConfigs,
} from './hog-function-utils'

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

describe('withoutSupersededPluginConfigs', () => {
    const pluginConfig = { id: 'plugin-1', template_id: 'plugin-customerio-plugin' } as HogFunctionType
    const migrated = (enabled: boolean): HogFunctionType =>
        ({
            id: 'hf-1',
            type: 'legacy_destination',
            template_id: 'plugin-customerio-plugin',
            enabled,
        }) as HogFunctionType

    it('hides a plugin config an enabled migrated destination replaces', () => {
        expect(withoutSupersededPluginConfigs([migrated(true)], [pluginConfig])).toEqual([])
    })

    it('keeps the plugin config when the migrated destination is disabled, because it runs again', () => {
        expect(withoutSupersededPluginConfigs([migrated(false)], [pluginConfig])).toEqual([pluginConfig])
    })

    it('keeps a plugin config no migrated destination covers', () => {
        const other = { id: 'plugin-2', template_id: 'plugin-hubspot-plugin' } as HogFunctionType
        expect(withoutSupersededPluginConfigs([migrated(true)], [other])).toEqual([other])
    })
})
