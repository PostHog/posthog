import type { AugmentedTeamSdkVersionsInfo } from '../../onboarding/shared/sdkHealth/sdkHealthLogic'
import {
    hasOutdatedWebSdk,
    legacyConditionsAreInactive,
    legacyUiShouldBeMinimized,
    mobileSamplingGaps,
    outdatedWebTrafficShare,
    TRIGGER_GROUPS_MIN_SDK_VERSION,
    WebRelease,
} from './replayTriggersLogic'

// Only the version + count of each release matter to mobileSamplingGaps, so the rest is left off.
function sdkData(releasesByLib: Record<string, WebRelease[]>): AugmentedTeamSdkVersionsInfo {
    return Object.fromEntries(
        Object.entries(releasesByLib).map(([lib, releases]) => [lib, { allReleases: releases }])
    ) as unknown as AugmentedTeamSdkVersionsInfo
}

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

    describe('legacyUiShouldBeMinimized', () => {
        const recentTraffic: WebRelease[] = [{ version: '1.400.0', count: 100 }]
        const outdatedTraffic: WebRelease[] = [{ version: '1.300.0', count: 100 }]

        it.each<[string, WebRelease[], boolean, boolean]>([
            // Recent traffic but no v2 groups: the SDK falls back to legacy, so it must stay visible.
            ['recent SDK, no v2 groups', recentTraffic, false, false],
            ['recent SDK, has v2 groups', recentTraffic, true, true],
            ['outdated SDK, has v2 groups', outdatedTraffic, true, false],
            ['no web data, has v2 groups', [], true, false],
        ])('%s -> %s', (_description, releases, hasV2Groups, expected) => {
            expect(legacyUiShouldBeMinimized(releases, hasV2Groups)).toBe(expected)
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

    describe('mobileSamplingGaps', () => {
        it('flags each mobile SDK with traffic below its sampling floor', () => {
            const gaps = mobileSamplingGaps(
                sdkData({
                    'posthog-android': [
                        { version: '3.33.0', count: 30 },
                        { version: '3.34.0', count: 70 },
                    ],
                    'posthog-ios': [{ version: '3.41.9', count: 50 }],
                })
            )
            expect(gaps).toEqual([
                { label: 'Android', minVersion: '3.34.0', outdatedCount: 30, totalCount: 100, share: 0.3 },
                { label: 'iOS', minVersion: '3.42.0', outdatedCount: 50, totalCount: 50, share: 1 },
            ])
        })

        it('ignores SDKs whose traffic is all at or above the floor', () => {
            const gaps = mobileSamplingGaps(
                sdkData({
                    'posthog-android': [{ version: '3.34.0', count: 100 }],
                    'posthog-react-native': [{ version: '5.0.0', count: 10 }],
                })
            )
            expect(gaps).toEqual([])
        })

        it('counts unparseable versions as below the floor', () => {
            const gaps = mobileSamplingGaps(sdkData({ 'posthog-ios': [{ version: 'unknown', count: 5 }] }))
            expect(gaps).toEqual([{ label: 'iOS', minVersion: '3.42.0', outdatedCount: 5, totalCount: 5, share: 1 }])
        })

        it('returns no gaps when there is no mobile data', () => {
            expect(mobileSamplingGaps(sdkData({ web: [{ version: '1.300.0', count: 100 }] }))).toEqual([])
        })
    })
})
