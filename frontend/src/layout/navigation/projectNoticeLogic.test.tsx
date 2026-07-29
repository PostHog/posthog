import { MOCK_TEAM_ID } from 'lib/api.mock'

import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { verifyEmailLogic } from 'scenes/authentication/verify-email/verifyEmailLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { projectNoticeLogic } from './projectNoticeLogic'

const DISMISS_KEY = 'project-notice-dismissed.missing_reverse_proxy'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

describe('projectNoticeLogic', () => {
    describe('proxy records conditional loading', () => {
        let getItemSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/organizations/:organization_id/proxy_records': [200, { results: [] }],
                },
            })
            initKeaTests()
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem')
        })

        afterEach(() => {
            getItemSpy.mockRestore()
            jest.useRealTimers()
        })

        it.each([
            { label: 'day of month is > 7', date: new Date(2026, 3, 15), dismissed: false },
            { label: 'notice is dismissed', date: new Date(2026, 3, 3), dismissed: true },
        ])('does not load proxy records when $label', async ({ date, dismissed }) => {
            jest.useFakeTimers()
            jest.setSystemTime(date)
            getItemSpy.mockImplementation((key: string) => (dismissed && key === DISMISS_KEY ? 'true' : null))

            const logic = projectNoticeLogic()
            logic.mount()

            await expectLogic(logic).toNotHaveDispatchedActions(['loadRecords'])
            expect(logic.values.proxyRecords).toBeNull()

            logic.unmount()
        })

        it('loads proxy records when day <= 7 and notice not dismissed', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date(2026, 3, 3)) // April 3

            getItemSpy.mockImplementation(() => null)

            const logic = projectNoticeLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadRecords'])

            logic.unmount()
        })
    })

    describe('unauthenticated session', () => {
        let getItemSpy: jest.SpyInstance
        let getDateSpy: jest.SpyInstance
        let originalAppContext: AppContext | undefined

        beforeEach(() => {
            originalAppContext = window.POSTHOG_APP_CONTEXT
            // Simulate a missing/expired session — userLogic boots to a null user.
            window.POSTHOG_APP_CONTEXT = {
                ...originalAppContext,
                current_user: null,
            } as unknown as AppContext
            useMocks({
                get: {
                    '/api/organizations/:organization_id/proxy_records': [200, { results: [] }],
                },
                post: {
                    '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
                },
            })
            initKeaTests()
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => null)
            // Inside the first-7-days nudge window, so only the auth guard can hold the fetch back.
            getDateSpy = jest.spyOn(Date.prototype, 'getDate').mockReturnValue(3)
        })

        afterEach(() => {
            getItemSpy.mockRestore()
            getDateSpy.mockRestore()
            window.POSTHOG_APP_CONTEXT = originalAppContext
        })

        it('does not load proxy records when the user is unauthenticated', async () => {
            const logic = projectNoticeLogic()
            logic.mount()

            await expectLogic(logic).toNotHaveDispatchedActions(['loadRecords'])
            expect(logic.values.proxyRecords).toBeNull()

            logic.unmount()
        })
    })

    describe.each([
        { status: 401, reason: 'missing or expired session' },
        { status: 403, reason: 'restricted org member below read access' },
    ])('proxy records $status handling', ({ status }) => {
        let getItemSpy: jest.SpyInstance
        let getDateSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                get: {
                    // Function form so the [status, body] tuple is honored — a static array value
                    // would be served as a 200 JSON body instead of the error status.
                    '/api/organizations/:organization_id/proxy_records': () => [status, {}],
                },
                post: {
                    '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
                },
            })
            initKeaTests()
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => null)
            getDateSpy = jest.spyOn(Date.prototype, 'getDate').mockReturnValue(3)
        })

        afterEach(() => {
            getItemSpy.mockRestore()
            getDateSpy.mockRestore()
        })

        it(`swallows a ${status} instead of surfacing a load failure`, async () => {
            const logic = projectNoticeLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadRecords', 'loadRecordsSuccess'])
            await expectLogic(logic).toNotHaveDispatchedActions(['loadRecordsFailure'])
            expect(logic.values.proxyRecords).toBeNull()

            logic.unmount()
        })
    })

    describe('reverse proxy checker connection', () => {
        let getItemSpy: jest.SpyInstance
        let getDateSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                get: {
                    // currentOrganizationId resolves to the loaded org id, not "@current" —
                    // match any id so loadRecords resolves instead of erroring.
                    '/api/organizations/:organization_id/proxy_records': [200, { results: [] }],
                },
                post: {
                    // reverseProxyCheckerLogic's HogQL detection query.
                    '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
                },
            })
            initKeaTests()
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => null)
            getDateSpy = jest.spyOn(Date.prototype, 'getDate')
        })

        afterEach(() => {
            getItemSpy.mockRestore()
            getDateSpy.mockRestore()
        })

        it.each([
            { label: 'inside the nudge window', dayOfMonth: 3 },
            { label: 'outside the nudge window', dayOfMonth: 15 },
        ])('mounts the connected checker $label and tears it down on unmount', async ({ dayOfMonth }) => {
            getDateSpy.mockReturnValue(dayOfMonth)

            const logic = projectNoticeLogic()
            logic.mount()

            // Connected via connect(), so it mounts with projectNoticeLogic regardless of the date gate.
            expect(reverseProxyCheckerLogic.isMounted()).toBe(true)
            // Let the auto-triggered detection settle so no async work outlives the test.
            await expectLogic(reverseProxyCheckerLogic).toDispatchActions(['loadHasReverseProxySuccess'])

            logic.unmount()
            expect(reverseProxyCheckerLogic.isMounted()).toBe(false)
        })
    })

    describe('reverse proxy banner suppression', () => {
        let getItemSpy: jest.SpyInstance
        let getDateSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/organizations/:organization_id/proxy_records': [200, { results: [] }],
                },
                post: {
                    '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
                },
            })
            initKeaTests()
            // isCloudOrDev gates the nudge — self-hosted users manage their own infrastructure.
            preflightLogic.actions.loadPreflightSuccess({ cloud: true } as any)
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => null)
            // Inside the first-7-days nudge window.
            getDateSpy = jest.spyOn(Date.prototype, 'getDate').mockReturnValue(3)
        })

        afterEach(() => {
            getItemSpy.mockRestore()
            getDateSpy.mockRestore()
        })

        // Drives the projectNoticeVariant selector deterministically: wait for the checker's
        // auto-load to settle, then force the detection result and an empty managed-proxy list so
        // the assertion doesn't depend on async msw timing. A forced value wins because it is
        // dispatched after the awaited auto-load.
        const mountWithDetectedProxy = async (
            hasReverseProxy: boolean
        ): Promise<ReturnType<typeof projectNoticeLogic>> => {
            const logic = projectNoticeLogic()
            logic.mount()
            await expectLogic(reverseProxyCheckerLogic).toDispatchActions(['loadHasReverseProxySuccess'])
            reverseProxyCheckerLogic.actions.loadHasReverseProxySuccess(hasReverseProxy)
            logic.actions.loadRecordsSuccess([])
            return logic
        }

        it('suppresses the nudge when a self-managed proxy is detected', async () => {
            const logic = await mountWithDetectedProxy(true)

            // Zero managed proxy records, but a DIY proxy is routing events — the banner must not nag.
            expect(logic.values.projectNoticeVariant).not.toEqual('missing_reverse_proxy')

            logic.unmount()
        })

        it('shows the nudge when no proxy exists and there are no managed records', async () => {
            const logic = await mountWithDetectedProxy(false)

            expect(logic.values.projectNoticeVariant).toEqual('missing_reverse_proxy')

            logic.unmount()
        })
    })

    describe('unverified email banner CTA', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/organizations/:organization_id/proxy_records': [200, { results: [] }],
                },
                post: {
                    '/api/users/request_email_verification/': [200, { success: true }],
                },
            })
            initKeaTests()
        })

        it('mounts verifyEmailLogic so the CTA reaches its request loader', async () => {
            const logic = projectNoticeLogic()
            logic.mount()

            // The banner renders on every scene, but verifyEmailLogic is otherwise only mounted on the
            // verify-email scene — without this connection the CTA action dispatches into an unmounted
            // logic and silently no-ops.
            expect(verifyEmailLogic.isMounted()).toBe(true)

            await expectLogic(verifyEmailLogic, () => {
                verifyEmailLogic.actions.requestVerificationLink('test-uuid')
            }).toDispatchActions(['requestVerificationLink', 'requestVerificationLinkSuccess'])

            logic.unmount()
        })
    })

    describe('social auth without a password', () => {
        const SOCIAL_DISMISS_KEY = 'project-notice-dismissed.social_auth_no_password'

        let getItemSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/organizations/:organization_id/proxy_records': [200, { results: [] }],
                },
            })
            initKeaTests()
            // Without email_service_available the unverified-email branch can't win the priority chain.
            preflightLogic.actions.loadPreflightSuccess({ cloud: true } as any)
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => null)
        })

        afterEach(() => {
            getItemSpy.mockRestore()
        })

        const mountWithUser = (user: Record<string, any>): ReturnType<typeof projectNoticeLogic> => {
            const logic = projectNoticeLogic()
            logic.mount()
            userLogic.actions.loadUserSuccess({
                has_social_auth: true,
                has_password: false,
                has_sso_enforcement: false,
                is_email_verified: true,
                ...user,
            } as any)
            return logic
        }

        it.each([
            { label: 'social login is the only credential', user: {}, dismissed: false, expected: true },
            { label: 'a password is already set', user: { has_password: true }, dismissed: false, expected: false },
            { label: 'the org enforces SSO', user: { has_sso_enforcement: true }, dismissed: false, expected: false },
            {
                label: 'the account has no social login',
                user: { has_social_auth: false },
                dismissed: false,
                expected: false,
            },
            { label: 'the nudge was already dismissed', user: {}, dismissed: true, expected: false },
        ])('shows the nudge: $expected when $label', async ({ user, dismissed, expected }) => {
            if (dismissed) {
                getItemSpy.mockImplementation((key: string) => (key === SOCIAL_DISMISS_KEY ? 'true' : null))
            }

            const logic = mountWithUser(user)

            expect(logic.values.projectNoticeVariant === 'social_auth_no_password').toBe(expected)

            logic.unmount()
        })

        it('offers a way to dismiss the nudge', async () => {
            const logic = mountWithUser({})

            // Without a dismiss key the banner renders no close button, so it would nag forever.
            expect(logic.values.projectNoticeDismissKey).toEqual('social_auth_no_password')
            expect(logic.values.projectNotice?.onClose).toBeTruthy()

            logic.unmount()
        })
    })

    describe('reverse proxy banner CTA navigation', () => {
        let getItemSpy: jest.SpyInstance
        let getDateSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/organizations/:organization_id/proxy_records': [200, { results: [] }],
                },
                post: {
                    '/api/environments/:team_id/query/:kind': () => [200, { results: [] }],
                },
            })
            initKeaTests()
            preflightLogic.actions.loadPreflightSuccess({ cloud: true } as any)
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => null)
            getDateSpy = jest.spyOn(Date.prototype, 'getDate').mockReturnValue(3)
        })

        afterEach(() => {
            getItemSpy.mockRestore()
            getDateSpy.mockRestore()
        })

        // The CTA used to be a mid-sentence inline <Link> in the banner message — a small, fragile
        // click target. A user clicked it and nothing happened (no navigation, no autocapture). It now
        // lives in the banner's `action` prop as a real button; this asserts that button still routes.
        it('navigates to the reverse proxy settings when the banner CTA is clicked', async () => {
            const logic = projectNoticeLogic()
            logic.mount()
            await expectLogic(reverseProxyCheckerLogic).toDispatchActions(['loadHasReverseProxySuccess'])
            reverseProxyCheckerLogic.actions.loadHasReverseProxySuccess(false)
            logic.actions.loadRecordsSuccess([])

            expect(logic.values.projectNoticeVariant).toEqual('missing_reverse_proxy')

            const notice = logic.values.projectNotice
            const { container } = render(
                <LemonBanner type={notice?.type || 'info'} action={notice?.action} onClose={notice?.onClose}>
                    {notice?.message}
                </LemonBanner>
            )

            // The banner renders the action at two responsive breakpoints, both sharing the data-attr.
            const cta = container.querySelector<HTMLElement>('[data-attr="missing-reverse-proxy-settings_link"]')
            expect(cta).not.toBeNull()

            await userEvent.click(cta!)

            // Routing prefixes the current project, so assert the settings target rather than an exact path.
            expect(router.values.location.pathname).toMatch(/\/settings\/organization-proxy$/)

            logic.unmount()
        })
    })
})
