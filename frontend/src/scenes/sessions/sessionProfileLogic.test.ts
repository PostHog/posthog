import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { sessionProfileLogic } from 'scenes/sessions/sessionProfileLogic'

import { initKeaTests } from '~/test/init'

const SESSION_ID = '01890000-0000-7000-8000-000000000000'

describe('sessionProfileLogic', () => {
    let logic: ReturnType<typeof sessionProfileLogic.build>

    beforeEach(async () => {
        initKeaTests()

        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.recordings, 'list').mockResolvedValue({ results: [] } as any)

        logic = sessionProfileLogic({ sessionId: SESSION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // A background query aborted mid-flight (usually a navigation) surfaces as one of these and must
    // resolve the loader rather than reject — a rejected loader reports the error to error tracking.
    const transientErrors: [string, unknown][] = [
        ['Chrome network abort', new TypeError('Failed to fetch')],
        ['Firefox network error', new TypeError('NetworkError when attempting to fetch resource.')],
        ['Safari network error', new TypeError('Load failed')],
        ['AbortError', Object.assign(new Error('Aborted'), { name: 'AbortError' })],
        ['wrapped fetch failure (ApiError, no status)', new ApiError('Failed to fetch', undefined)],
    ]

    it.each(transientErrors)('swallows a transient error (%s) instead of failing the loader', async (_desc, error) => {
        jest.spyOn(api, 'queryHogQL').mockRejectedValue(error)

        await expectLogic(logic, () => {
            logic.actions.loadSupportTicketEvents()
        }).toDispatchActions(['loadSupportTicketEvents', 'loadSupportTicketEventsSuccess'])

        expect(logic.values.supportTicketEvents).toEqual([])
    })

    it('still surfaces a genuine query failure', async () => {
        jest.spyOn(api, 'queryHogQL').mockRejectedValue(new ApiError('Internal error', 500))

        await expectLogic(logic, () => {
            logic.actions.loadSupportTicketEvents()
        }).toDispatchActions(['loadSupportTicketEvents', 'loadSupportTicketEventsFailure'])
    })
})
