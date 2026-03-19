import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

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
        beforeEach(async () => {
            await expectLogic(userLogic, () => {
                userLogic.actions.loadUser()
            })
                .toDispatchActions(['loadUserSuccess'])
                .toMatchValues({ user: userWithLightTheme, themeMode: 'light' })
        })

        it('themeMode updates immediately when updateUser is called with theme_mode', async () => {
            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ theme_mode: 'dark' })
            }).toMatchValues({
                themeMode: 'dark',
                optimisticThemeMode: 'dark',
            })
        })

        it('optimisticThemeMode is cleared and themeMode comes from user when update succeeds', async () => {
            const updatedUser = { ...userWithLightTheme, theme_mode: 'dark' as const }
            useMocks({
                patch: {
                    '/api/users/@me/': () => [200, updatedUser],
                },
            })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ theme_mode: 'dark' })
            }).toMatchValues({ themeMode: 'dark', optimisticThemeMode: 'dark' })

            await expectLogic(userLogic).toDispatchActions(['updateUserSuccess']).toMatchValues({
                user: updatedUser,
                themeMode: 'dark',
                optimisticThemeMode: null,
            })
        })

        it('optimisticThemeMode is cleared and themeMode reverts to user when update fails', async () => {
            useMocks({
                patch: {
                    '/api/users/@me/': () => [500, { detail: 'Server error' }],
                },
            })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ theme_mode: 'dark' })
            }).toMatchValues({ themeMode: 'dark', optimisticThemeMode: 'dark' })

            await expectLogic(userLogic).toDispatchActions(['updateUserFailure']).toMatchValues({
                user: userWithLightTheme,
                themeMode: 'light',
                optimisticThemeMode: null,
            })
        })

        it('updateUser without theme_mode does not change optimisticThemeMode', async () => {
            // Keep update requests in-flight so success/failure handlers cannot clear optimisticThemeMode mid-test.
            useMocks({
                patch: {
                    '/api/users/@me/': async () => await new Promise(() => undefined),
                },
            })

            userLogic.actions.updateUser({ theme_mode: 'dark' })
            await expectLogic(userLogic).toMatchValues({ optimisticThemeMode: 'dark' })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ first_name: 'Jane' })
            }).toMatchValues({ optimisticThemeMode: 'dark' })
        })
    })
})
