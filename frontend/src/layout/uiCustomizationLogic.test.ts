import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { UserUIConfiguration } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import {
    mergeUIConfigurations,
    orderKeys,
    uiCustomizationLogic,
    withKeyMovedAmong,
    withSidebarItemVisibility,
    withSidebarSectionVisibility,
} from './uiCustomizationLogic'

describe('uiCustomizationLogic', () => {
    let logic: ReturnType<typeof uiCustomizationLogic.build>
    let patchedUser: Partial<UserType> | null
    let patchCount: number

    function seedUser(uiConfiguration: UserUIConfiguration | null): void {
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, ui_configuration: uiConfiguration })
    }

    beforeEach(() => {
        patchedUser = null
        patchCount = 0
        useMocks({
            patch: {
                '/api/users/@me/': async ({ request }) => {
                    patchCount += 1
                    patchedUser = (await request.json()) as Partial<UserType>
                    return [200, { ...MOCK_DEFAULT_USER, ...patchedUser }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.UI_CUSTOMIZATION], {
            [FEATURE_FLAGS.UI_CUSTOMIZATION]: true,
        })
        logic = uiCustomizationLogic()
        logic.mount()
    })

    it('ignores stored configuration while the customization flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        seedUser({
            version: 1,
            sidebar: {
                sections: { recents: { visible: false } },
                items: { data: { visible: false } },
            },
        })

        expect(logic.values.isSidebarItemShown('data')).toBe(true)
        expect(logic.values.isSidebarSectionShown('recents')).toBe(true)
    })

    it('shows everything when the user has no configuration', () => {
        seedUser(null)

        expect(logic.values.isSidebarItemShown('data')).toBe(true)
        expect(logic.values.isSidebarSectionShown('my_tools')).toBe(true)
    })

    it('hides only elements explicitly configured as hidden', () => {
        seedUser({
            version: 1,
            sidebar: {
                sections: { recents: { visible: false } },
                items: { data: { visible: false }, home: { visible: true } },
            },
        })

        expect(logic.values.isSidebarItemShown('data')).toBe(false)
        expect(logic.values.isSidebarItemShown('home')).toBe(true)
        expect(logic.values.isSidebarItemShown('files')).toBe(true)
        expect(logic.values.isSidebarSectionShown('recents')).toBe(false)
        expect(logic.values.isSidebarSectionShown('project')).toBe(true)
    })

    it('applies a toggle optimistically and persists the complete configuration', async () => {
        seedUser({ version: 1, sidebar: { items: { starred: { visible: false } } } })

        await expectLogic(logic, () => {
            logic.actions.setSidebarItemShown('data', false)
        }).toFinishAllListeners()

        expect(logic.values.isSidebarItemShown('data')).toBe(false)
        expect(logic.values.isSidebarItemShown('starred')).toBe(false)
        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            sidebar: { items: { starred: { visible: false }, data: { visible: false } } },
        })
    })

    it('batches rapid consecutive changes into a single PATCH', async () => {
        seedUser(null)

        await expectLogic(logic, () => {
            logic.actions.setSidebarItemShown('data', false)
            logic.actions.setSidebarItemShown('files', false)
            logic.actions.setSidebarFlattened(true)
        }).toFinishAllListeners()

        expect(patchCount).toBe(1)
        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            sidebar: {
                items: { data: { visible: false }, files: { visible: false } },
                flattened: true,
            },
        })
    })

    it('inherits the project default but persists only the user layer on a tweak', async () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            default_ui_configuration: {
                version: 1,
                sidebar: { items: { inbox: { visible: false } }, density: 'compact' },
            },
        })
        seedUser(null)

        // The project default applies to a member without personal customization...
        expect(logic.values.isSidebarItemShown('inbox')).toBe(false)
        expect(logic.values.sidebarDensity).toBe('compact')

        await expectLogic(logic, () => {
            logic.actions.setSidebarItemShown('files', false)
        }).toFinishAllListeners()

        // ...and a personal tweak layers on top without snapshotting the default,
        // so later default changes still reach this user.
        expect(logic.values.isSidebarItemShown('inbox')).toBe(false)
        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            sidebar: { items: { files: { visible: false } } },
        })
    })

    it('merges the project default under the user configuration per key', () => {
        const projectDefault: UserUIConfiguration = {
            version: 1,
            sidebar: {
                items: { data: { visible: false }, files: { visible: false } },
                density: 'compact',
                itemOrder: ['data', 'home'],
            },
        }
        const userConfiguration: UserUIConfiguration = {
            version: 1,
            sidebar: { items: { files: { visible: true } }, itemOrder: ['home', 'data'] },
        }

        // No personal configuration: the project default applies wholesale.
        expect(mergeUIConfigurations(projectDefault, null)).toEqual(projectDefault)
        // Personal keys win; unrelated default keys shine through; orderings are not merged element-wise.
        expect(mergeUIConfigurations(projectDefault, userConfiguration)).toEqual({
            version: 1,
            sidebar: {
                sections: {},
                items: { data: { visible: false }, files: { visible: true } },
                density: 'compact',
                itemOrder: ['home', 'data'],
            },
            projects: {},
        })
    })

    it('applies stored orders ignoring unknown keys and appending unlisted ones', () => {
        expect(orderKeys(['a', 'b', 'c', 'd'], ['c', 'x', 'a'])).toEqual(['c', 'a', 'b', 'd'])
        expect(orderKeys(['a', 'b'], null)).toEqual(['a', 'b'])
        expect(orderKeys(['a', 'b'], [])).toEqual(['a', 'b'])
    })

    it('moves items relative to their visible neighbors, skipping hidden ones', () => {
        // 'b' is hidden: moving 'c' up must land before 'a', not invisibly swap with 'b'.
        expect(withKeyMovedAmong(['a', 'b', 'c'], ['a', 'c'], 'c', -1)).toEqual(['c', 'a', 'b'])
        expect(withKeyMovedAmong(['a', 'b', 'c'], ['a', 'c'], 'a', 1)).toEqual(['b', 'c', 'a'])
        // Edge positions cannot move further.
        expect(withKeyMovedAmong(['a', 'b', 'c'], ['a', 'c'], 'a', -1)).toBeNull()
        expect(withKeyMovedAmong(['a', 'b', 'c'], ['a', 'c'], 'c', 1)).toBeNull()
    })

    it('helpers add visibility without dropping the rest of the configuration', () => {
        const existing: UserUIConfiguration = {
            version: 2,
            sidebar: {
                sections: { recents: { visible: false } },
                items: { data: { visible: false } },
            },
        }

        expect(withSidebarItemVisibility(existing, 'files', false)).toEqual({
            version: 2,
            sidebar: {
                sections: { recents: { visible: false } },
                items: { data: { visible: false }, files: { visible: false } },
            },
        })
        expect(withSidebarSectionVisibility(null, 'my_tools', false)).toEqual({
            version: 1,
            sidebar: { sections: { my_tools: { visible: false } } },
        })
    })
})
