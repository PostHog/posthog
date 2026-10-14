import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { UserUIConfiguration } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { uiCustomizationLogic } from './uiCustomizationLogic'

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
        logic = uiCustomizationLogic()
        logic.mount()
    })

    it('completes the starred setup optimistically without dropping the rest of the configuration', async () => {
        seedUser({ version: 1, sidebar: { density: 'compact' }, sql_editor: { vim_mode_enabled: true } })

        await expectLogic(logic, () => {
            logic.actions.completeStarredProductsSetup()
        }).toFinishAllListeners()

        expect(logic.values.starredProductsSetupCompleted).toBe(true)
        expect(patchedUser?.ui_configuration).toEqual({
            version: 1,
            sidebar: { density: 'compact', starred_products_setup_completed: true },
            sql_editor: { vim_mode_enabled: true },
        })
    })
})
