import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    hasOutdatedWebSdk,
    legacyConditionsAreInactive,
    legacyUiShouldBeMinimized,
    outdatedWebTrafficShare,
    replayTriggersLogic,
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

    describe('saving URL triggers', () => {
        let logic: ReturnType<typeof replayTriggersLogic.build>

        beforeEach(() => {
            useMocks({
                patch: {
                    '/api/environments/:id': async ({ request }) => [
                        200,
                        { ...MOCK_DEFAULT_TEAM, ...((await request.json()) as Record<string, any>) },
                    ],
                },
            })
            initKeaTests()
            logic = replayTriggersLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        // Guards the regression this fixes: the write must not be fire-and-forget. If the save reverts
        // to closing the form before the PATCH settles (or drops the in-flight flag), the ordering below
        // breaks, since it asserts the flag brackets the team update and the form closes only afterwards.
        it('holds the in-flight flag until the team update resolves, then closes the form', async () => {
            logic.actions.newUrlTrigger()
            expect(logic.values.editUrlTriggerIndex).toBe(-1)

            await expectLogic(logic, () => {
                logic.actions.addUrlTrigger({ url: '^https://example.com/checkout$', matching: 'regex' })
            }).toDispatchActions([
                (action) => action.type === logic.actionTypes.setIsSavingUrlTrigger && action.payload.saving === true,
                teamLogic.actionTypes.updateCurrentTeamSuccess,
                (action) => action.type === logic.actionTypes.setIsSavingUrlTrigger && action.payload.saving === false,
                (action) =>
                    action.type === logic.actionTypes.setEditUrlTriggerIndex && action.payload.originalIndex === null,
            ])

            expect(logic.values.isSavingUrlTrigger).toBe(false)
            expect(logic.values.editUrlTriggerIndex).toBeNull()
            expect(logic.values.urlTriggerConfig).toEqual([
                { url: '^https://example.com/checkout$', matching: 'regex' },
            ])
        })
    })
})
