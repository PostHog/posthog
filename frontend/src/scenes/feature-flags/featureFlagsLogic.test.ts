import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { showApprovalRequiredToast } from 'scenes/approvals/ApprovalRequiredBanner'
import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'
import {
    FeatureFlagsFilters,
    FeatureFlagsTab,
    featureFlagsLogic,
    flagMatchesFilters,
    flagMatchesSearch,
    flagMatchesStatus,
    flagMatchesType,
} from 'scenes/feature-flags/featureFlagsLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

jest.mock('scenes/approvals/ApprovalRequiredBanner', () => ({
    showApprovalRequiredToast: jest.fn(),
}))

describe('flagMatchesSearch', () => {
    const flag = { ...NEW_FLAG, id: 1, key: 'my-feature', name: 'My Feature Flag' } as FeatureFlagType

    it.each<[string | undefined, boolean]>([
        [undefined, true],
        ['my', true],
        ['MY-FEATURE', true],
        ['flag', true],
        ['nonexistent', false],
    ])('search=%p → %p', (search, expected) => {
        expect(flagMatchesSearch(flag, search)).toBe(expected)
    })

    describe('regex-based search', () => {
        const webAnalyticsFlag = {
            ...NEW_FLAG,
            id: 2,
            key: 'web-analytics',
            name: 'Web Analytics Feature',
        } as FeatureFlagType
        const webUnderscoreFlag = { ...NEW_FLAG, id: 3, key: 'web_dashboard', name: 'Test Flag' } as FeatureFlagType
        const webSpaceFlag = { ...NEW_FLAG, id: 4, key: 'web analytics', name: 'Space Flag' } as FeatureFlagType
        const flagWithExperiment = {
            ...NEW_FLAG,
            id: 5,
            key: 'experiment-flag',
            name: 'Experiment Flag',
            experiment_set: [1],
            experiment_set_metadata: [{ id: 1, name: 'My Experiment Test', is_running: false }],
        } as FeatureFlagType

        it.each<[FeatureFlagType, string, boolean]>([
            // Regex pattern searches - spaces match any separator
            [webAnalyticsFlag, 'web ana', true], // "web ana" matches "web-analytics"
            [webUnderscoreFlag, 'web dash', true], // "web dash" matches "web_dashboard"
            [webSpaceFlag, 'web ana', true], // "web ana" matches "web analytics"
            [webAnalyticsFlag, 'web analytics', true], // Should match name

            // Experiment name searches
            [flagWithExperiment, 'experiment test', true], // Should match experiment name
            [flagWithExperiment, 'my experiment', true], // Should match experiment name
            [flagWithExperiment, 'experiment', true], // Should match flag name

            // Searches that shouldn't match
            [webAnalyticsFlag, 'web mobile', false], // "mobile" not in "web-analytics"
            [webUnderscoreFlag, 'web mobile', false], // "mobile" not in flag
            [flagWithExperiment, 'mobile test', false], // "mobile" not in flag or experiment

            // Single word searches (existing behavior)
            [webAnalyticsFlag, 'web', true],
            [webAnalyticsFlag, 'analytics', true],
            [webAnalyticsFlag, 'mobile', false],
            [flagWithExperiment, 'experiment', true],

            // Test trimming
            [webAnalyticsFlag, 'web ', true], // Trailing space should be trimmed
            [webAnalyticsFlag, ' web', true], // Leading space should be trimmed
            [webAnalyticsFlag, '  web  ', true], // Multiple spaces should be trimmed
        ])('flag=%p search=%p → %p', (testFlag, search, expected) => {
            expect(flagMatchesSearch(testFlag, search)).toBe(expected)
        })

        it('handles null experiment names safely', () => {
            const flagWithNullExperimentName = {
                ...NEW_FLAG,
                id: 5,
                key: 'null-test-flag',
                name: 'Flag with Null Test',
                experiment_set: [2],
                experiment_set_metadata: [{ id: 2, name: null as any, is_running: false }],
            } as FeatureFlagType

            // Should not throw error and should still match by flag name
            expect(flagMatchesSearch(flagWithNullExperimentName, 'flag')).toBe(true)
            // Should not match by experiment name since it's null
            expect(flagMatchesSearch(flagWithNullExperimentName, 'experiment')).toBe(false)
            // Should not throw when searching for something that would only match the null experiment name
            expect(flagMatchesSearch(flagWithNullExperimentName, 'nonexistent')).toBe(false)
        })

        it('handles regex metacharacters safely', () => {
            const testFlag = { ...NEW_FLAG, id: 6, key: 'test[flag]', name: 'Test (Flag)' } as FeatureFlagType

            // Should not throw error and should match using escaped regex
            expect(() => flagMatchesSearch(testFlag, '[flag]')).not.toThrow()
            expect(() => flagMatchesSearch(testFlag, '(Flag)')).not.toThrow()
            expect(() => flagMatchesSearch(testFlag, '*invalid')).not.toThrow()
            expect(() => flagMatchesSearch(testFlag, '?invalid')).not.toThrow()

            // Should match literal characters
            expect(flagMatchesSearch(testFlag, '[flag]')).toBe(true)
            expect(flagMatchesSearch(testFlag, '(Flag)')).toBe(true)
        })
    })
})

describe('flagMatchesStatus', () => {
    it.each<[boolean, FeatureFlagType['status'], string | undefined, boolean]>([
        [true, 'ACTIVE', undefined, true],
        [true, 'ACTIVE', 'true', true],
        [true, 'ACTIVE', 'false', false],
        [false, 'ACTIVE', 'false', true],
        [true, 'STALE', 'STALE', true],
        [true, 'ACTIVE', 'STALE', false],
    ])('active=%p status=%p filter=%p → %p', (active, status, filter, expected) => {
        const flag = { ...NEW_FLAG, id: 1, key: 'test', active, status } as FeatureFlagType
        expect(flagMatchesStatus(flag, filter)).toBe(expected)
    })
})

describe('flagMatchesType', () => {
    const flags = {
        boolean: { ...NEW_FLAG, id: 1, key: 'bool', filters: { groups: [] } } as FeatureFlagType,
        multivariant: {
            ...NEW_FLAG,
            id: 2,
            key: 'multi',
            filters: { groups: [], multivariate: { variants: [{ key: 'a', rollout_percentage: 100 }] } },
        } as FeatureFlagType,
        experiment: { ...NEW_FLAG, id: 3, key: 'exp', experiment_set: [1] } as FeatureFlagType,
        remote_config: { ...NEW_FLAG, id: 4, key: 'remote', is_remote_configuration: true } as FeatureFlagType,
    }

    it.each<[keyof typeof flags, string | undefined, boolean]>([
        ['boolean', undefined, true],
        ['boolean', 'boolean', true],
        ['boolean', 'multivariant', false],
        ['multivariant', 'multivariant', true],
        ['experiment', 'experiment', true],
        ['remote_config', 'remote_config', true],
    ])('%s with type=%p → %p', (flagKey, type, expected) => {
        expect(flagMatchesType(flags[flagKey], type)).toBe(expected)
    })
})

describe('flagMatchesFilters', () => {
    const base = { ...NEW_FLAG, id: 1, key: 'test', active: true } as FeatureFlagType

    describe('archived filter', () => {
        const liveFlag = { ...base, archived: false } as FeatureFlagType
        const archivedFlag = { ...base, archived: true } as FeatureFlagType

        it.each<[string, FeatureFlagType, Partial<FeatureFlagsFilters>, boolean]>([
            ['hides archived by default', archivedFlag, {}, false],
            ['shows live flags by default', liveFlag, {}, true],
            ['shows archived when archived=true', archivedFlag, { archived: 'true' }, true],
            ['hides live when archived=true', liveFlag, { archived: 'true' }, false],
        ])('%s', (_label, flag, filters, expected) => {
            expect(flagMatchesFilters(flag, filters as FeatureFlagsFilters)).toBe(expected)
        })
    })

    describe('excluded_tags filter', () => {
        const flagWithTag = { ...base, archived: false, tags: ['beta', 'internal'] } as FeatureFlagType
        const flagWithoutTag = { ...base, archived: false, tags: ['beta'] } as FeatureFlagType

        it.each<[string, FeatureFlagType, Partial<FeatureFlagsFilters>, boolean]>([
            ['excludes a flag whose tag matches excluded_tags', flagWithTag, { excluded_tags: ['internal'] }, false],
            [
                'keeps a flag whose tags do not match excluded_tags',
                flagWithoutTag,
                { excluded_tags: ['internal'] },
                true,
            ],
            ['keeps a flag when excluded_tags is empty', flagWithTag, { excluded_tags: [] }, true],
            [
                'keeps an untagged flag when excluded_tags is set',
                // Deliberately undefined tags to exercise the optional-chaining guard in flagMatchesFilters.
                { ...base, tags: undefined } as unknown as FeatureFlagType,
                { excluded_tags: ['internal'] },
                true,
            ],
            [
                'excluded_tags wins over tags when both match',
                flagWithTag,
                { tags: ['beta'], excluded_tags: ['beta'] },
                false,
            ],
        ])('%s', (_label, flag, filters, expected) => {
            expect(flagMatchesFilters(flag, filters as FeatureFlagsFilters)).toBe(expected)
        })
    })

    describe('creator filter', () => {
        const flagByUser = (id: number | null): FeatureFlagType =>
            ({
                ...base,
                archived: false,
                created_by: id == null ? null : ({ id } as FeatureFlagType['created_by']),
            }) as FeatureFlagType

        it.each<[string, number | null, number[] | undefined, boolean]>([
            ['no filter set matches any flag', 7, undefined, true],
            ['no filter set matches a creatorless flag', null, undefined, true],
            ['no filter set matches a creatorless flag with empty list', null, [], true],
            ['author in the list matches', 7, [7], true],
            ['author in a multi-id list matches', 7, [3, 7], true],
            ['author absent from the list does not match', 7, [3, 5], false],
            ['creatorless flag is excluded once a filter is set', null, [7], false],
        ])('%s', (_name, createdById, createdByIdFilter, expected) => {
            expect(flagMatchesFilters(flagByUser(createdById), { created_by_id: createdByIdFilter })).toBe(expected)
        })
    })
})

describe('the feature flags logic', () => {
    let logic: ReturnType<typeof featureFlagsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = featureFlagsLogic()
        logic.mount()
    })

    it('starts with active tab as "overview"', async () => {
        await expectLogic(logic).toMatchValues({ activeTab: FeatureFlagsTab.OVERVIEW })
    })

    it('can set tab to "history"', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.HISTORY)
        }).toMatchValues({ activeTab: FeatureFlagsTab.HISTORY })
        expect(router.values.searchParams['tab']).toEqual('history')
    })

    it('can set tab back to "overview"', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.HISTORY)
            logic.actions.setActiveTab(FeatureFlagsTab.OVERVIEW)
        }).toMatchValues({ activeTab: FeatureFlagsTab.OVERVIEW })
        expect(router.values.searchParams['tab']).toEqual('overview')
    })

    it('ignores unexpected tab keys', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.HISTORY)
            logic.actions.setActiveTab('tomato' as FeatureFlagsTab)
        }).toMatchValues({
            activeTab: FeatureFlagsTab.HISTORY,
        })
        expect(router.values.searchParams['tab']).toEqual('history')
    })

    it('sets the tab from the URL', async () => {
        await expectLogic(logic, () => {
            logic.actions.setActiveTab(FeatureFlagsTab.OVERVIEW)
            router.actions.push(urls.featureFlags(), { tab: 'history' })
        }).toMatchValues({
            activeTab: FeatureFlagsTab.HISTORY,
        })
    })

    describe('activity deep-link', () => {
        it('preserves the activity deep-link param when staying on the history tab', async () => {
            router.actions.push(urls.featureFlags(), { tab: 'history', activity: 'some-uuid' })
            await expectLogic(logic, () => {
                logic.actions.setActiveTab(FeatureFlagsTab.HISTORY)
            })
            expect(router.values.searchParams['activity']).toEqual('some-uuid')
        })

        it('drops the activity deep-link param when switching away from the history tab', async () => {
            router.actions.push(urls.featureFlags(), { tab: 'history', activity: 'some-uuid' })
            await expectLogic(logic, () => {
                logic.actions.setActiveTab(FeatureFlagsTab.OVERVIEW)
            })
            expect(router.values.searchParams['activity']).toBeUndefined()
        })
    })
})

describe('updateFeatureFlag 409 handling', () => {
    let logic: ReturnType<typeof featureFlagsLogic.build>

    // Every test here rejects updateFeatureFlag on purpose; kea-loaders would log each failure
    beforeEach(silenceKeaLoadersErrors)
    afterEach(resumeKeaLoadersErrors)

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:projectId/feature_flags/': () => [
                    200,
                    {
                        results: [{ id: 1, key: 'test-flag', active: false }],
                        count: 1,
                    },
                ],
            },
        })
        initKeaTests()
        logic = featureFlagsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        { active: true, expected: 'enable this feature flag' },
        { active: false, expected: 'disable this feature flag' },
    ])(
        'shows approval toast with "$expected" when toggling active=$active gets a 409',
        async ({ active, expected }) => {
            const error = { status: 409, data: { change_request_id: 'cr-123' } }
            jest.spyOn(api, 'update').mockRejectedValueOnce(error)

            logic.actions.updateFeatureFlag({ id: 1, payload: { active } })
            await expectLogic(logic).toFinishAllListeners()

            expect(showApprovalRequiredToast).toHaveBeenCalledWith('cr-123', expected)
        }
    )

    it('does not show approval toast for non-409 errors', async () => {
        const error = { status: 500, data: { detail: 'Internal server error' } }
        jest.spyOn(api, 'update').mockRejectedValueOnce(error)

        logic.actions.updateFeatureFlag({ id: 1, payload: { active: true } })
        await expectLogic(logic).toFinishAllListeners()

        expect(showApprovalRequiredToast).not.toHaveBeenCalled()
    })

    it('does not show approval toast for 409 without change_request_id', async () => {
        const error = { status: 409, data: { detail: 'Conflict' } }
        jest.spyOn(api, 'update').mockRejectedValueOnce(error)

        logic.actions.updateFeatureFlag({ id: 1, payload: { active: true } })
        await expectLogic(logic).toFinishAllListeners()

        expect(showApprovalRequiredToast).not.toHaveBeenCalled()
    })
})
