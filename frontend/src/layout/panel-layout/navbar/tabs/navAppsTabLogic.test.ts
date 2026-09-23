import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import preflight from '~/mocks/fixtures/_preflight.json'
import { initKeaTests } from '~/test/init'
import { ActivityTab, PreflightStatus, Region } from '~/types'

import * as decisionsApi from 'products/ml_inference/frontend/generated/api'
import type { DecideRequestApi, DecideResponseApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { appsItemName, groupApps } from './appsCatalog'
import { APPS_STARRED_TREE_KEY, navAppsTabLogic } from './navAppsTabLogic'

function answerApps(request: DecideRequestApi): DecideResponseApi {
    return {
        model: 'jev-1.13.0',
        input_tokens: 100,
        latency_ms: null,
        answers: Object.fromEntries(
            Object.entries(request.questions).map(([id, question]) => [
                id,
                {
                    type: 'noul',
                    probability: question.instructions.includes('"name":"Session replay"')
                        ? 0.95
                        : question.instructions.includes('"name":"Product analytics"')
                          ? 0.5
                          : 0.1,
                    choice: null,
                    score: null,
                    confidence: null,
                    probabilities: null,
                },
            ])
        ),
    }
}

describe('navAppsTabLogic', () => {
    beforeEach(() => {
        initKeaTests()
        navAppsTabLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ ...(preflight as unknown as PreflightStatus), is_debug: false })
    })

    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it.each([
        [false, Region.EU, true, false],
        [false, Region.US, false, false],
        [false, Region.US, true, true],
        [true, Region.DEV, false, true],
    ] as const)('matches API availability for debug=%s region=%s flag=%s', (debug, region, flag, expected) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: flag })
        preflightLogic.actions.loadPreflightSuccess({
            ...(preflight as unknown as PreflightStatus),
            region,
            is_debug: debug,
        })
        expect(navAppsTabLogic.values.jevEnabled).toBe(expected)
    })

    it('ranks all visible apps using the tooltip descriptions and examples, then culls weak matches', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        const decide = jest
            .spyOn(decisionsApi, 'mlInferenceDecisionsDecideCreate')
            .mockImplementation(async (_, request) => answerApps(request))
        await expectLogic(navAppsTabLogic, () =>
            navAppsTabLogic.actions.setSearch('watch a failed checkout')
        ).toDispatchActions(['setSearchSuccess'])
        expect(navAppsTabLogic.values.groupedItems.flatMap((group) => group.items.map(appsItemName))).toEqual([
            'Session replay',
            'Product analytics',
        ])
        const questions = decide.mock.calls.flatMap(([, request]) => Object.values(request.questions))
        expect(questions).toHaveLength(navAppsTabLogic.values.allItems.length)
        expect(
            questions.find((question) => question.instructions.includes('"name":"Session replay"'))?.instructions
        ).toContain('Watch a failed checkout to see what got in the way.')
        expect(
            decide.mock.calls.every(
                ([, request]) => request.model === 'jev-1.13.0' && Object.keys(request.questions).length <= 32
            )
        ).toBe(true)
        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setSearch('  ')).toDispatchActions([
            'setSearchSuccess',
        ])
        expect(navAppsTabLogic.values.groupedItems.flatMap((group) => group.items)).toHaveLength(
            navAppsTabLogic.values.allItems.length
        )
    })

    it.each(['failure', 'invalid_score'] as const)('falls back to name matching after %s', async (failure) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        jest.spyOn(decisionsApi, 'mlInferenceDecisionsDecideCreate').mockImplementation(async (_, request) => {
            if (failure === 'failure') {
                throw new Error('Unavailable')
            }
            const response = answerApps(request)
            Object.values(response.answers)[0].probability = 2
            return response
        })
        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setSearch('replay')).toDispatchActions([
            'setSearchSuccess',
        ])
        expect(navAppsTabLogic.values.appRankings?.failed).toBe(true)
        expect(navAppsTabLogic.values.groupedItems.flatMap((group) => group.items.map(appsItemName))).toEqual([
            'Replay vision',
            'Session replay',
        ])
    })

    it('debounces typing and discards answers when the search is cleared', async () => {
        jest.useFakeTimers()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true })
        const pending: (() => void)[] = []
        const decide = jest
            .spyOn(decisionsApi, 'mlInferenceDecisionsDecideCreate')
            .mockImplementation(
                (_, request) => new Promise((resolve) => pending.push(() => resolve(answerApps(request))))
            )
        navAppsTabLogic.actions.setSearch('watch')
        navAppsTabLogic.actions.setSearch('watch checkout')
        expect(decide).not.toHaveBeenCalled()
        await jest.advanceTimersByTimeAsync(250)
        expect(decide).toHaveBeenCalled()
        expect(decide.mock.calls.every(([, request]) => request.state.includes('watch checkout'))).toBe(true)
        navAppsTabLogic.actions.setSearch('')
        pending.forEach((resolve) => resolve())
        await jest.advanceTimersByTimeAsync(0)
        expect(navAppsTabLogic.values.appRankings).toBeNull()
        expect(navAppsTabLogic.values.appRankingsLoading).toBe(false)
        expect(navAppsTabLogic.values.groupedItems.flatMap((group) => group.items)).toHaveLength(
            navAppsTabLogic.values.allItems.length
        )
    })

    it.each([false, true])('retains every existing product and data destination with flags enabled: %s', (enabled) => {
        const registry = [...getDefaultTreeProducts(), ...getDefaultTreeDataAndPeople()]
        const flags = Object.fromEntries(registry.flatMap((item) => (item.flag ? [[item.flag, enabled]] : [])))
        featureFlagLogic.actions.setFeatureFlags([], flags)
        const expected = new Set([
            urls.projectRoot(),
            urls.activity(ActivityTab.ExploreEvents),
            ...registry.filter((item) => item.href && (!item.flag || enabled)).map((item) => item.href),
            ...projectTreeDataLogic.values.groupItems
                .filter((item) => item.href && (!item.flag || flags[item.flag]))
                .map((item) => item.href),
        ])
        const actual = navAppsTabLogic.values.groupedItems.flatMap((group) => group.items.map((item) => item.href))
        expect(new Set(actual)).toEqual(expected)
        expect(actual).toHaveLength(expected.size)
    })

    it('searches display names and preserves person ordering alongside dynamic groups', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true })
        expect(navAppsTabLogic.values.groupedItems[0].items.map(appsItemName)).toEqual([
            'Home',
            'Self-driving',
            'Activity',
        ])
        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setSearch('  self-driving  ')).toMatchValues({
            groupedItems: [
                {
                    label: 'Project',
                    items: [expect.objectContaining({ href: urls.inbox(), path: 'Inbox', tags: ['beta'] })],
                },
            ],
        })
        const groups = groupApps(
            [
                { path: 'Cohorts', category: 'People', href: '/cohorts', visualOrder: 20 },
                { path: 'Persons', category: 'People', href: '/persons', visualOrder: 10 },
                { path: 'group_0', displayLabel: 'Organizations', category: 'Groups', href: '/groups/0' },
            ],
            ''
        )
        expect(groups.find((group) => group.label === 'People')?.items.map(appsItemName)).toEqual([
            'Persons',
            'Cohorts',
        ])
        expect(
            groupApps(
                groups.flatMap((group) => group.items),
                'organizations'
            )[0].items[0].href
        ).toEqual('/groups/0')
    })

    it('filters starred apps with the app search', async () => {
        const starredTree = projectTreeLogic({
            key: APPS_STARRED_TREE_KEY,
            root: 'shortcuts://',
            shortcutScope: 'apps',
        })
        await expectLogic(navAppsTabLogic, () => navAppsTabLogic.actions.setSearch('onboarding')).toDispatchActions([
            starredTree.actionTypes.setSearchTerm,
        ])
        expect(starredTree.values.searchTerm).toEqual('onboarding')
    })
    it.each([
        ['apps', ['Product analytics']],
        ['files', ['Overview', 'Research']],
        [undefined, ['Product analytics', 'Overview', 'Research']],
    ] as const)('keeps starred items in their own section: %s', (shortcutScope, expected) => {
        projectTreeDataLogic.actions.loadShortcutsSuccess([
            { id: 'app', path: 'Product analytics', type: 'product_analytics', href: '/insights' },
            { id: 'file', path: 'Overview', type: 'dashboard', ref: '1', href: '/dashboard/1' },
            { id: 'folder', path: 'Research', type: 'folder', ref: 'Research' },
        ])
        const tree = projectTreeLogic({ key: `scoped-${shortcutScope}`, root: 'shortcuts://', shortcutScope })
        tree.mount()
        expect(tree.values.fullFileSystemFiltered.map((item) => item.name)).toEqual(expected)
        tree.actions.setSearchTerm('Product analytics')
        expect(tree.values.fullFileSystemFiltered.map((item) => item.name)).toEqual(
            shortcutScope === 'files' ? [] : ['Product analytics']
        )
    })
})
