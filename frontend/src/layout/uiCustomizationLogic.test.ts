import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { UserUIConfiguration } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import {
    uiCustomizationLogic,
    withSidebarItemVisibility,
    withSidebarPatch,
    withSidebarSectionVisibility,
} from './uiCustomizationLogic'

describe('uiCustomizationLogic', () => {
    let logic: ReturnType<typeof uiCustomizationLogic.build>
    let patchedUser: Partial<UserType> | null

    function seedUser(uiConfiguration: UserUIConfiguration | null): void {
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, ui_configuration: uiConfiguration })
    }

    beforeEach(() => {
        patchedUser = null
        useMocks({
            patch: {
                '/api/users/@me/': async ({ request }) => {
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

    it('defaults to comfortable density when no configuration is set', () => {
        seedUser(null)
        expect(logic.values.sidebarDensity).toBe('comfortable')
    })

    it('returns the stored density from the configuration', () => {
        seedUser({
            version: 1,
            sidebar: { density: 'compact' },
        })
        expect(logic.values.sidebarDensity).toBe('compact')
    })

    it('ignores stored density when the customization flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        seedUser({
            version: 1,
            sidebar: { density: 'compact' },
        })
        expect(logic.values.sidebarDensity).toBe('comfortable')
    })

    it('persists density change optimistically', async () => {
        seedUser({ version: 1, sidebar: { density: 'comfortable' } })

        await expectLogic(logic, () => {
            logic.actions.setSidebarDensity('compact')
        }).toFinishAllListeners()

        expect(logic.values.sidebarDensity).toBe('compact')
        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            sidebar: { density: 'compact' },
        })
    })

    it('withSidebarPatch merges density into configuration', () => {
        expect(withSidebarPatch(null, { density: 'compact' })).toEqual({
            version: 1,
            sidebar: { density: 'compact' },
        })
        expect(
            withSidebarPatch({ version: 1, sidebar: { items: { data: { visible: false } } } }, { density: 'compact' })
        ).toEqual({
            version: 1,
            sidebar: { items: { data: { visible: false } }, density: 'compact' },
        })
    })
})
