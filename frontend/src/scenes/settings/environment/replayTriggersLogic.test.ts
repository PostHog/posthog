import {
    hasOutdatedWebSdk,
    legacyConditionsAreInactive,
    outdatedWebTrafficShare,
    TRIGGER_GROUPS_MIN_SDK_VERSION,
    WebRelease,
} from './replayTriggersLogic'

describe('replayTriggersLogic', () => {
    describe('legacyConditionsAreInactive', () => {
        it.each<[string, WebRelease[], boolean]>([
            ['no web data', [], false],
            [
                'only new versions',
                [
                    { version: '1.369.0', count: 100 },
                    { version: '1.400.1', count: 100 },
                ],
                true,
            ],
            [
                'only old versions',
                [
                    { version: '1.300.0', count: 100 },
                    { version: '1.368.9', count: 100 },
                ],
                false,
            ],
            [
                'tiny outdated tail stays inactive',
                [
                    { version: '1.300.0', count: 6 },
                    { version: '1.400.0', count: 100000 },
                ],
                true,
            ],
            [
                'outdated share above threshold is not inactive',
                [
                    { version: '1.300.0', count: 30 },
                    { version: '1.400.0', count: 70 },
                ],
                false,
            ],
            ['exactly the minimum version', [{ version: TRIGGER_GROUPS_MIN_SDK_VERSION, count: 100 }], true],
            [
                'unparseable version counts as outdated',
                [
                    { version: 'not-a-version', count: 50 },
                    { version: '1.400.0', count: 50 },
                ],
                false,
            ],
        ])('%s -> %s', (_description, releases, expected) => {
            expect(legacyConditionsAreInactive(releases)).toBe(expected)
        })
    })

    describe('hasOutdatedWebSdk', () => {
        it.each<[string, WebRelease[], boolean]>([
            ['no web data', [], false],
            [
                'only new versions',
                [
                    { version: '1.369.0', count: 100 },
                    { version: '1.400.1', count: 100 },
                ],
                false,
            ],
            [
                'only old versions',
                [
                    { version: '1.300.0', count: 100 },
                    { version: '1.368.9', count: 100 },
                ],
                true,
            ],
            [
                'tiny outdated tail does not warn',
                [
                    { version: '1.300.0', count: 6 },
                    { version: '1.400.0', count: 100000 },
                ],
                false,
            ],
            [
                'outdated share above threshold warns',
                [
                    { version: '1.300.0', count: 30 },
                    { version: '1.400.0', count: 70 },
                ],
                true,
            ],
            ['exactly the minimum version', [{ version: TRIGGER_GROUPS_MIN_SDK_VERSION, count: 100 }], false],
            [
                'unparseable version counts as outdated',
                [
                    { version: 'not-a-version', count: 50 },
                    { version: '1.400.0', count: 50 },
                ],
                true,
            ],
        ])('%s -> %s', (_description, releases, expected) => {
            expect(hasOutdatedWebSdk(releases)).toBe(expected)
        })
    })

    describe('outdatedWebTrafficShare', () => {
        it.each<[string, WebRelease[], { outdatedCount: number; totalCount: number; share: number }]>([
            ['no web data', [], { outdatedCount: 0, totalCount: 0, share: 0 }],
            [
                'just below the 5% threshold',
                [
                    { version: '1.300.0', count: 4 },
                    { version: '1.400.0', count: 96 },
                ],
                { outdatedCount: 4, totalCount: 100, share: 0.04 },
            ],
            [
                'at the 5% threshold',
                [
                    { version: '1.300.0', count: 5 },
                    { version: '1.400.0', count: 95 },
                ],
                { outdatedCount: 5, totalCount: 100, share: 0.05 },
            ],
        ])('%s', (_description, releases, expected) => {
            expect(outdatedWebTrafficShare(releases)).toEqual(expected)
        })

        it('treats the 5% threshold as inclusive for warnings', () => {
            const atThreshold: WebRelease[] = [
                { version: '1.300.0', count: 5 },
                { version: '1.400.0', count: 95 },
            ]
            expect(hasOutdatedWebSdk(atThreshold)).toBe(true)
            expect(legacyConditionsAreInactive(atThreshold)).toBe(false)
        })
    })
})
