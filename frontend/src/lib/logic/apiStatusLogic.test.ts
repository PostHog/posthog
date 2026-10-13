import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { MakeLogicType, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { apiStatusLogic } from './apiStatusLogic'

const MOCK_IMPERSONATED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_impersonated: true,
    is_impersonated_read_only: true,
    is_impersonated_until: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
    },
}

describe('apiStatusLogic', () => {
    let logic: ReturnType<typeof apiStatusLogic.build>

    describe('401 handling during impersonation', () => {
        it('skips auto-logout on 401 for impersonated users', async () => {
            useMocks({
                get: {
                    '/api/users/@me/': () => [401, {}],
                },
            })
            initKeaTests()
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_IMPERSONATED_USER)

            logic = apiStatusLogic()
            logic.mount()

            const logoutSpy = jest.spyOn(userLogic.actions, 'logout')

            const mockResponse = { status: 401, ok: false } as Response

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(mockResponse)
            }).toFinishAllListeners()

            expect(logoutSpy).not.toHaveBeenCalled()
            logoutSpy.mockRestore()
        })

        it.each([
            ['an expired session', {}, undefined],
            ['an access rule refusal', { code: 'access_blocked' }, 'access_blocked'],
        ])('triggers auto-logout on 401 for non-impersonated users, for %s', async (_, body, reason) => {
            // The real logout listener submits a <form>, which jsdom doesn't implement
            let submitted: HTMLFormElement | undefined
            const submitSpy = jest
                .spyOn(HTMLFormElement.prototype, 'submit')
                .mockImplementation(function (this: HTMLFormElement) {
                    submitted = this
                })
            useMocks({
                get: {
                    '/api/users/@me/': () => [401, body],
                },
            })
            initKeaTests()
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

            logic = apiStatusLogic()
            logic.mount()

            const logoutSpy = jest.spyOn(userLogic.actions, 'logout')

            const mockResponse = { status: 401, ok: false } as Response

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(mockResponse)
            }).toFinishAllListeners()

            expect(logoutSpy).toHaveBeenCalledWith(true, undefined, reason)
            // The /logout view turns the reason into the message the login page shows.
            expect((submitted?.elements.namedItem('reason') as HTMLInputElement | null)?.value).toBe(reason)
            logoutSpy.mockRestore()
            submitSpy.mockRestore()
        })
    })

    describe('read-only impersonation 403 handling', () => {
        const READ_ONLY_DETAIL = 'This action is not allowed during read-only user impersonation.'
        let errorSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                patch: {
                    '/api/users/@me/': () => [403, { code: 'impersonation_read_only', detail: READ_ONLY_DETAIL }],
                },
            })
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()
            errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('toast-id')
        })

        afterEach(() => {
            jest.restoreAllMocks()
            document.body.innerHTML = ''
        })

        const blockedWrite = (): Promise<unknown> => api.update('api/users/@me/', {}).catch(() => null)

        const loaderThatWrites = async (): Promise<void> => {
            const writeLogic = kea<MakeLogicType<{ savedUser: null }, { saveUser: () => void }>>([
                path(['lib', 'logic', 'apiStatusLogic', 'test', 'writeLogic']),
                loaders({
                    savedUser: [
                        null,
                        {
                            saveUser: async () => {
                                await api.update('api/users/@me/', {})
                                return null
                            },
                        },
                    ],
                }),
            ])
            writeLogic.mount()
            await expectLogic(writeLogic, () => writeLogic.actions.saveUser()).toDispatchActions(['saveUserFailure'])
        }

        const clickThatWrites = async (tag: 'button' | 'a', beforeWrite?: () => void): Promise<void> => {
            const element = document.createElement(tag)
            if (tag === 'a') {
                element.setAttribute('href', '#')
            }
            document.body.appendChild(element)
            let write: Promise<unknown> = Promise.resolve()
            element.addEventListener('click', (event) => {
                event.preventDefault()
                beforeWrite?.()
                write = blockedWrite()
            })
            element.click()
            await write
        }

        // LemonFormDialog submits from its own keydown handler, with no click or submit event. On a link,
        // a real browser writes from the click that follows the keydown, which jsdom does not fire.
        const keyThatWrites = async (
            key: string,
            tag: 'input' | 'a' = 'input',
            init: KeyboardEventInit = {}
        ): Promise<void> => {
            const element = document.createElement(tag)
            if (tag === 'a') {
                element.setAttribute('href', '?tab=other')
            }
            document.body.appendChild(element)
            let write: Promise<unknown> = Promise.resolve()
            element.addEventListener('keydown', () => {
                write = blockedWrite()
            })
            element.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...init }))
            await write
        }

        it.each([
            ['a button click', () => clickThatWrites('button')],
            [
                'a click that only changed the search params',
                () =>
                    clickThatWrites('button', () =>
                        router.actions.replace(router.values.location.pathname, { tab: 'other' })
                    ),
            ],
            [
                'a form submit without a button',
                async () => {
                    const form = document.createElement('form')
                    document.body.appendChild(form)
                    let write: Promise<unknown> = Promise.resolve()
                    form.addEventListener('submit', (event) => {
                        event.preventDefault()
                        write = blockedWrite()
                    })
                    form.requestSubmit()
                    await write
                },
            ],
            ['Enter in a dialog input', () => keyThatWrites('Enter')],
            [
                'an Enter that confirms an IME composition',
                () => keyThatWrites('Enter', 'input', { isComposing: true, keyCode: 229 }),
            ],
        ])('toasts when %s starts the blocked write', async (_name, run) => {
            await run()
            await expectLogic(logic).toFinishAllListeners()

            expect(errorSpy).toHaveBeenCalledWith(READ_ONLY_DETAIL, { hideButton: true })
        })

        it.each([
            ['no click started it', blockedWrite],
            ['a kea loader sent it', loaderThatWrites],
            ['typing in an input started it', () => keyThatWrites('a')],
            ['Enter on a link started it', () => keyThatWrites('Enter', 'a')],
            ['a link click started it', () => clickThatWrites('a')],
            ['the click navigated first', () => clickThatWrites('button', () => router.actions.push('/elsewhere'))],
            [
                'a click finished before it started',
                async () => {
                    document.body.click()
                    await new Promise((resolve) => setTimeout(resolve, 0))
                    await blockedWrite()
                },
            ],
        ])('does not toast when %s', async (_name, run) => {
            await run()
            await expectLogic(logic).toFinishAllListeners()

            expect(errorSpy).not.toHaveBeenCalled()
        })

        it('does not toast for unrelated 403s', async () => {
            const mockResponse = {
                status: 403,
                ok: false,
                json: () => Promise.resolve({ code: 'permission_denied', detail: 'Nope' }),
            } as unknown as Response

            await expectLogic(logic, () => {
                logic.actions.onApiResponse(mockResponse, undefined, true)
            }).toFinishAllListeners()

            expect(errorSpy).not.toHaveBeenCalled()
        })
    })

    describe('writes that need a fresh session', () => {
        const STALE_SESSION = { type: 'authentication_error', code: 'sensitive_action_required_reauth' }
        let patchCalls: number

        beforeEach(() => {
            patchCalls = 0
            useMocks({
                patch: {
                    '/api/users/@me/': () => (++patchCalls === 1 ? [403, STALE_SESSION] : [200, { saved: true }]),
                },
                post: {
                    '/api/personal_api_keys/': () => [403, STALE_SESSION],
                },
            })
            initKeaTests()
            logic = apiStatusLogic()
            logic.mount()
            timeSensitiveAuthenticationLogic.mount()
        })

        it.each([
            ['success', { value: { saved: true } }, 2],
            ['failure', { error: expect.objectContaining({ status: 403, code: STALE_SESSION.code }) }, 1],
        ] as const)(
            'on re-authentication %s, settles the write as %o after %i request(s)',
            async (outcome, expected, calls) => {
                const result = api.update('api/users/@me/', { notification_settings: {} }).then(
                    (value) => ({ value }),
                    (error) => ({ error })
                )
                await expectLogic(logic).toDispatchActions(['setTimeSensitiveAuthenticationRequired'])
                logic.actions.resolveSensitiveAction(outcome)

                expect(await result).toEqual(expected)
                expect(patchCalls).toBe(calls)
            }
        )

        it('settles every write waiting on the same re-authentication', async () => {
            const first = api.update('api/users/@me/', { theme_mode: 'dark' }).catch(() => 'first settled')
            const second = api.create('api/personal_api_keys/', {}).catch(() => 'second settled')
            await expectLogic(logic).toDispatchActions([
                'setTimeSensitiveAuthenticationRequired',
                'setTimeSensitiveAuthenticationRequired',
            ])
            logic.actions.resolveSensitiveAction('failure')

            expect(await Promise.all([first, second])).toEqual(['first settled', 'second settled'])
        })

        it('keeps the write waiting after a wrong password', async () => {
            const result = api.update('api/users/@me/', { notification_settings: {} })
            await expectLogic(logic).toDispatchActions(['setTimeSensitiveAuthenticationRequired'])

            timeSensitiveAuthenticationLogic.actions.submitReauthenticationFailure(new Error('Wrong password'), {})
            expect(patchCalls).toBe(1)
            logic.actions.resolveSensitiveAction('success')

            expect(await result).toEqual({ saved: true })
        })
    })
})
