import { hasOutdatedWebSdk, legacyConditionsAreInactive, TRIGGER_GROUPS_MIN_SDK_VERSION } from './replayTriggersLogic'

describe('replayTriggersLogic', () => {
    describe('legacyConditionsAreInactive', () => {
        it.each([
            ['no web data', [], false],
            ['only new versions', ['1.369.0', '1.400.1'], true],
            ['only old versions', ['1.300.0', '1.368.9'], false],
            ['mix of old and new', ['1.368.0', '1.400.0'], false],
            ['exactly the minimum version', [TRIGGER_GROUPS_MIN_SDK_VERSION], true],
            ['unparseable version stays conservative', ['not-a-version', '1.400.0'], false],
        ])('%s -> %s', (_description, versions, expected) => {
            expect(legacyConditionsAreInactive(versions as string[])).toBe(expected)
        })
    })

    describe('hasOutdatedWebSdk', () => {
        it.each([
            ['no web data', [], false],
            ['only new versions', ['1.369.0', '1.400.1'], false],
            ['only old versions', ['1.300.0', '1.368.9'], true],
            ['mix of old and new', ['1.368.0', '1.400.0'], true],
            ['exactly the minimum version', [TRIGGER_GROUPS_MIN_SDK_VERSION], false],
            ['unparseable version stays conservative', ['not-a-version', '1.400.0'], true],
        ])('%s -> %s', (_description, versions, expected) => {
            expect(hasOutdatedWebSdk(versions as string[])).toBe(expected)
        })
    })
})
