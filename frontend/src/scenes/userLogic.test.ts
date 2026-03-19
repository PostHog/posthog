import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { userLogic } from './userLogic'

describe('userLogic', () => {
    const userWithLightTheme = { ...MOCK_DEFAULT_USER, theme_mode: 'light' as const }

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/users/@me/': () => [200, userWithLightTheme],
            },
        })
        userLogic.mount()
    })

    describe('optimistic theme mode', () => {
        afterEach(() => {
            jest.restoreAllMocks()
        })

        beforeEach(async () => {
            await expectLogic(userLogic, () => {
                userLogic.actions.loadUser()
            })
                .toDispatchActions(['loadUserSuccess'])
                .toMatchValues({ user: userWithLightTheme, themeMode: 'light' })
        })

        it('themeMode updates immediately when updateUser is called with theme_mode', async () => {
            jest.spyOn(api, 'update').mockImplementation(async () => await new Promise(() => undefined))

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ theme_mode: 'dark' })
            }).toMatchValues({
                themeMode: 'dark',
                optimisticThemeMode: 'dark',
            })
        })

        it('optimisticThemeMode is cleared and themeMode comes from user when update succeeds', async () => {
            const updatedUser = { ...userWithLightTheme, theme_mode: 'dark' as const }
            jest.spyOn(api, 'update').mockImplementation(async () => await new Promise(() => undefined))

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ theme_mode: 'dark' })
            }).toMatchValues({ themeMode: 'dark', optimisticThemeMode: 'dark' })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUserSuccess(updatedUser)
            }).toMatchValues({
                user: updatedUser,
                themeMode: 'dark',
                optimisticThemeMode: null,
            })
        })

        it('optimisticThemeMode is cleared and themeMode reverts to user when update fails', async () => {
            jest.spyOn(api, 'update').mockImplementation(async () => await new Promise(() => undefined))

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ theme_mode: 'dark' })
            }).toMatchValues({ themeMode: 'dark', optimisticThemeMode: 'dark' })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUserFailure('Server error')
            }).toMatchValues({
                user: userWithLightTheme,
                themeMode: 'light',
                optimisticThemeMode: null,
            })
        })

        it('updateUser without theme_mode does not change optimisticThemeMode', async () => {
            jest.spyOn(api, 'update').mockImplementation(async () => await new Promise(() => undefined))

            userLogic.actions.updateUser({ theme_mode: 'dark' })
            await expectLogic(userLogic).toMatchValues({ optimisticThemeMode: 'dark' })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ first_name: 'Jane' })
            }).toMatchValues({ optimisticThemeMode: 'dark' })
        })
    })
})
