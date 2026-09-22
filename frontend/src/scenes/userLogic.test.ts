import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
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

    describe('user details form', () => {
        afterEach(() => {
            jest.restoreAllMocks()
        })

        beforeEach(async () => {
            // The load started on mount must settle first, or its result overwrites the seeded user.
            await expectLogic(userLogic).toFinishAllListeners()
            userLogic.actions.loadUserSuccess(userWithLightTheme)
        })

        test.each([
            {
                name: 'a name-only save sends no current_password',
                changes: { first_name: 'Renamed' },
                expected: { first_name: 'Renamed', email: userWithLightTheme.email },
            },
            {
                name: 'an email change sends the current password',
                changes: { email: 'new-address@example.com', current_password: 'hunter2hunter2' },
                expected: { email: 'new-address@example.com', current_password: 'hunter2hunter2' },
            },
        ])('$name', async ({ changes, expected }) => {
            jest.spyOn(api, 'update').mockResolvedValue(userWithLightTheme)
            const updateUserSpy = jest.spyOn(userLogic.actions, 'updateUser')

            userLogic.actions.setUserDetailsValues(changes)
            await expectLogic(userLogic, () => {
                userLogic.actions.submitUserDetails()
            }).toFinishAllListeners()

            expect(updateUserSpy).toHaveBeenCalledTimes(1)
            const payload = updateUserSpy.mock.calls[0][0]
            expect(payload).toMatchObject(expected)
            expect('current_password' in payload).toBe('current_password' in expected)
        })
    })

    describe('updateUser failure handling', () => {
        beforeEach(silenceKeaLoadersErrors)
        afterEach(resumeKeaLoadersErrors)

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('dispatches updateUserFailure (not success) when the backend rejects the update', async () => {
            jest.spyOn(api, 'update').mockRejectedValue({
                status: 400,
                detail: 'Update rejected by server.',
            })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ email: 'new@example.com' })
            })
                .toDispatchActions(['updateUserFailure'])
                .toNotHaveDispatchedActions(['updateUserSuccess'])
        })

        it('keeps the existing user when the update fails — no silent revert via success', async () => {
            jest.spyOn(api, 'update').mockRejectedValue({ status: 400, detail: 'nope' })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ email: 'new@example.com' })
            })
                .toDispatchActions(['updateUserFailure'])
                .toMatchValues({ user: userWithLightTheme })
        })

        it.each([502, 503, 504])(
            'does not report transient gateway error %s to error tracking but still fails the update',
            async (status) => {
                const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
                jest.spyOn(api, 'update').mockRejectedValue({ status, statusText: 'Bad Gateway' })

                await expectLogic(userLogic, () => {
                    userLogic.actions.updateUser({ email: 'new@example.com' })
                })
                    .toDispatchActions(['updateUserFailure'])
                    .toNotHaveDispatchedActions(['updateUserSuccess'])

                expect(captureSpy).not.toHaveBeenCalled()
            }
        )

        it('reports a genuine backend error (500) to error tracking', async () => {
            const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
            jest.spyOn(api, 'update').mockRejectedValue({ status: 500, statusText: 'Internal Server Error' })

            await expectLogic(userLogic, () => {
                userLogic.actions.updateUser({ email: 'new@example.com' })
            }).toDispatchActions(['updateUserFailure'])

            expect(captureSpy).toHaveBeenCalled()
        })
    })
})
