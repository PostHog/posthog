import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { reverseProxyCheckerLogic } from 'lib/components/ReverseProxyChecker/reverseProxyCheckerLogic'
import { verifyEmailLogic } from 'scenes/authentication/verify-email/verifyEmailLogic'

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

    describe('self-managed reverse proxy detection', () => {
        let getItemSpy: jest.SpyInstance

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/organizations/@current/proxy_records': [200, { results: [] }],
                },
                post: {
                    // reverseProxyCheckerLogic's HogQL detection query — a non-null
                    // $lib_custom_api_host means a DIY proxy is routing events.
                    '/api/environments/:team_id/query/:kind': () => [
                        200,
                        { results: [['https://proxy.example.com'], [null]] },
                    ],
                },
            })
            initKeaTests()
            getItemSpy = jest.spyOn(Storage.prototype, 'getItem')
        })

        afterEach(() => {
            getItemSpy.mockRestore()
            jest.useRealTimers()
        })

        it('mounts the proxy checker and runs detection inside the nudge window', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date(2026, 3, 3)) // April 3
            getItemSpy.mockImplementation(() => null)

            const logic = projectNoticeLogic()
            logic.mount()

            expect(reverseProxyCheckerLogic.isMounted()).toBe(true)
            await expectLogic(reverseProxyCheckerLogic).toDispatchActions(['loadHasReverseProxySuccess'])
            expect(reverseProxyCheckerLogic.values.hasReverseProxy).toBe(true)

            logic.unmount()
            expect(reverseProxyCheckerLogic.isMounted()).toBe(false)
        })

        it('does not mount the proxy checker outside the nudge window', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date(2026, 3, 15)) // April 15
            getItemSpy.mockImplementation(() => null)

            const logic = projectNoticeLogic()
            logic.mount()

            expect(reverseProxyCheckerLogic.isMounted()).toBe(false)

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
