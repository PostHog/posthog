import { promotePosthogCustomMetadata } from './custom-metadata'

describe('promotePosthogCustomMetadata', () => {
    it.each([
        ['posthog_tags', 'tags', ['beta', 'internal']],
        ['posthog_environment', 'environment', 'prod'],
    ])('promotes <namespace>%s to %s with the prefix stripped', (suffix, name, value) => {
        const props: Record<string, unknown> = { [`ns.${suffix}`]: value }
        promotePosthogCustomMetadata(props, 'ns.')
        expect(props[name]).toEqual(value)
    })

    it.each([
        ['a non-posthog key', 'ns.org_id', 'org_id'],
        ['a reserved $-prefixed name', 'ns.posthog_$ai_model', '$ai_model'],
        ['the reserved distinct_id name', 'ns.posthog_distinct_id', 'distinct_id'],
    ])('does not promote %s', (_label, key, resultName) => {
        const props: Record<string, unknown> = { [key]: 'value' }
        promotePosthogCustomMetadata(props, 'ns.')
        expect(props[resultName]).toBeUndefined()
    })

    it('does not overwrite an existing property', () => {
        const props: Record<string, unknown> = { tags: ['keep'], 'ns.posthog_tags': ['drop'] }
        promotePosthogCustomMetadata(props, 'ns.')
        expect(props['tags']).toEqual(['keep'])
    })
})
