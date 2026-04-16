import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

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

        it('does not load proxy records when day of month is > 7', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date(2026, 3, 15)) // April 15

            const logic = projectNoticeLogic()
            logic.mount()

            await expectLogic(logic).toNotHaveDispatchedActions(['loadRecords'])
            expect(logic.values.proxyRecords).toBeNull()

            logic.unmount()
        })

        it('does not load proxy records when notice is dismissed', async () => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date(2026, 3, 3)) // April 3

            getItemSpy.mockImplementation((key: string) => (key === DISMISS_KEY ? 'true' : null))

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
})
