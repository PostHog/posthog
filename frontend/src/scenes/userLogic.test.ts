import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { userLogic } from './userLogic'

describe('userLogic', () => {
    const userWithLightTheme = { ...MOCK_DEFAULT_USER, theme_mode: 'light' as const }

    beforeEach(() => {
        // Set current_user before initKeaTests so userLogic bootstraps with theme_mode: 'light'
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            current_user: userWithLightTheme,
        } as any
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

    describe('realtime notification preferences', () => {
        let updateUserSpy: jest.SpyInstance

        beforeEach(() => {
            updateUserSpy = jest.spyOn(userLogic.actions, 'updateUser')
        })

        afterEach(() => {
            updateUserSpy.mockRestore()
        })

        it('updateRealtimeNotificationForTeam sends a minimal patch toggling one (type, team) pair to disabled', () => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                notification_settings: {
                    ...MOCK_DEFAULT_USER.notification_settings,
                    realtime_notifications_disabled: {},
                },
            } as any)

            userLogic.actions.updateRealtimeNotificationForTeam('comment_mention', 42, false)

            expect(updateUserSpy).toHaveBeenCalledWith({
                notification_settings: expect.objectContaining({
                    realtime_notifications_disabled: { comment_mention: { '42': true } },
                }),
            })
        })

        it('updateRealtimeNotificationForProject sets every passed type to disabled for that team', () => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                notification_settings: {
                    ...MOCK_DEFAULT_USER.notification_settings,
                    realtime_notifications_disabled: {},
                },
            } as any)

            userLogic.actions.updateRealtimeNotificationForProject(7, ['comment_mention', 'alert_firing'], false)

            expect(updateUserSpy).toHaveBeenCalledWith({
                notification_settings: expect.objectContaining({
                    realtime_notifications_disabled: {
                        comment_mention: { '7': true },
                        alert_firing: { '7': true },
                    },
                }),
            })
        })

        it('updateAllRealtimeNotifications disables every (team, type) pair when enabled=false', () => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                notification_settings: {
                    ...MOCK_DEFAULT_USER.notification_settings,
                    realtime_notifications_disabled: {},
                },
            } as any)

            userLogic.actions.updateAllRealtimeNotifications([1, 2], ['comment_mention'], false)

            expect(updateUserSpy).toHaveBeenCalledWith({
                notification_settings: expect.objectContaining({
                    realtime_notifications_disabled: {
                        comment_mention: { '1': true, '2': true },
                    },
                }),
            })
        })

        it('updateAllRealtimeNotifications clears disabled entries when enabled=true', () => {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                notification_settings: {
                    ...MOCK_DEFAULT_USER.notification_settings,
                    realtime_notifications_disabled: { comment_mention: { '1': true, '2': true } },
                },
            } as any)

            userLogic.actions.updateAllRealtimeNotifications([1, 2], ['comment_mention'], true)

            expect(updateUserSpy).toHaveBeenCalledWith({
                notification_settings: expect.objectContaining({
                    realtime_notifications_disabled: {
                        comment_mention: { '1': false, '2': false },
                    },
                }),
            })
        })
    })
})
