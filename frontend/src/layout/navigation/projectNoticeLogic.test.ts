import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { verifyEmailLogic } from 'scenes/authentication/verify-email/verifyEmailLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

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
                    '/api/organizations/@current/proxy_records': [200, { results: [] }],
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
                    '/api/organizations/@current/proxy_records': [200, { results: [] }],
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
})
