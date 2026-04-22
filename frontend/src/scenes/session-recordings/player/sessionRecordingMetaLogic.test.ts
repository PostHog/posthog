import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingMetaLogic } from 'scenes/session-recordings/player/sessionRecordingMetaLogic'

import { silenceKeaLoadersErrors } from '~/initKea'

import { setupSessionRecordingTest } from './__mocks__/test-setup'

jest.mock('./snapshot-processing/DecompressionWorkerManager')

describe('sessionRecordingMetaLogic', () => {
    let logic: ReturnType<typeof sessionRecordingMetaLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest()
        featureFlagLogic.mount()
        apiStatusLogic.mount()
        logic = sessionRecordingMetaLogic({ sessionRecordingId: '2', playerKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    // Regression guard for a raw `TypeError: Failed to fetch` surfacing as an uncaught
    // async rejection when the browser cannot complete the request (offline, CORS
    // preflight failure, aborted navigation). The loader must convert this into a
    // tagged `loadRecordingMetaFailure` so the existing `loadMetaError` reducer handles
    // it gracefully instead of the exception bubbling through to error tracking.
    describe('loadRecordingMeta network failure handling', () => {
        it('converts a raw TypeError from fetch into a tagged loadRecordingMetaFailure', async () => {
            silenceKeaLoadersErrors()
            jest.spyOn(api.recordings, 'get').mockRejectedValueOnce(new TypeError('Failed to fetch'))

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()

            expect(logic.values.isNotFound).toBe(false)
            expect(logic.values.loadMetaError).toBe(true)
        })

        // Verifies the loader pipes the network error into apiStatusLogic so the
        // internet-connection banner stays consistent. In production `handleFetch`
        // already fires this for the raw TypeError (the banner detection keys off
        // `error?.message === 'Failed to fetch'`) — the loader's explicit call is a
        // belt-and-suspenders pass-through that also keeps the banner wired up when
        // the failure arrives via ApiError wrapping.
        it('pipes the network error through apiStatusLogic.onApiResponse', async () => {
            silenceKeaLoadersErrors()
            jest.spyOn(api.recordings, 'get').mockRejectedValueOnce(new TypeError('Failed to fetch'))

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()

            await expectLogic(apiStatusLogic).toDispatchActions(['onApiResponse'])
        })

        // handleFetch wraps raw `TypeError`s as `ApiError` with an undefined status — the
        // loader must treat these as network failures too, not as real HTTP errors.
        it('treats ApiError with undefined status (wrapped by handleFetch) as a network failure', async () => {
            silenceKeaLoadersErrors()
            jest.spyOn(api.recordings, 'get').mockRejectedValueOnce(
                new ApiError('TypeError: Failed to fetch', undefined)
            )

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()

            expect(logic.values.loadMetaError).toBe(true)
            expect(logic.values.isNotFound).toBe(false)
        })

        it('preserves the 404 ApiError path so isNotFound still flips', async () => {
            silenceKeaLoadersErrors()
            jest.spyOn(api.recordings, 'get').mockRejectedValueOnce(new ApiError('Not found', 404))

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()

            expect(logic.values.isNotFound).toBe(true)
            expect(logic.values.loadMetaError).toBe(false)
        })

        it('preserves non-404 HTTP errors on loadMetaError', async () => {
            silenceKeaLoadersErrors()
            jest.spyOn(api.recordings, 'get').mockRejectedValueOnce(new ApiError('Internal Server Error', 500))

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()

            expect(logic.values.loadMetaError).toBe(true)
            expect(logic.values.isNotFound).toBe(false)
        })
    })
})
