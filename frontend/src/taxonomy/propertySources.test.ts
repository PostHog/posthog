import { getExternalPropertySource, getPropertyValueUrl } from './propertySources'

describe('propertySources', () => {
    test.each([
        ['eas/account', 'acme', 'https://expo.dev/accounts/acme'],
        ['eas/build_id', 'b1', 'https://expo.dev/builds/b1'],
        ['eas/project_id', 'p1', 'https://expo.dev/projects/p1'],
        ['eas/update_id', 'u1', 'https://expo.dev/updates/u1'],
        ['eas/workflow_id', 'w1', 'https://expo.dev/workflows/w1'],
    ])('links %s to its page on expo.dev', (key, value, expected) => {
        expect(getPropertyValueUrl(key, value)).toEqual(expected)
    })

    test.each([
        ['eas/channel', 'production'],
        ['eas/runtime_version', '1.0.0'],
        ['$current_url', 'https://example.com'],
        ['easy_mode', 'on'],
    ])('does not link %s', (key, value) => {
        expect(getPropertyValueUrl(key, value)).toBeNull()
    })

    test.each([
        ['a non-string value', 42],
        ['a blank value', '   '],
        ['a missing value', undefined],
    ])('does not link an Expo property with %s', (_, value) => {
        expect(getPropertyValueUrl('eas/build_id', value)).toBeNull()
    })

    it('escapes the value into the path', () => {
        expect(getPropertyValueUrl('eas/account', 'acme/../evil?x=1')).toEqual(
            'https://expo.dev/accounts/acme%2F..%2Fevil%3Fx%3D1'
        )
    })

    test.each([
        ['eas/build_id', 'expo'],
        ['langfuse trace', 'langfuse'],
    ])('recognizes %s as coming from %s', (key, expected) => {
        expect(getExternalPropertySource(key)?.id).toEqual(expected)
    })

    test.each([['$current_url'], ['plan'], [null]])('recognizes no source for %s', (key) => {
        expect(getExternalPropertySource(key)).toBeNull()
    })
})
