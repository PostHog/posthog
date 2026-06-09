import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { MockSignature } from '~/mocks/utils'

import recordingEventsJson from '../__mocks__/recording_events_query'
import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { sessionEventsDataLogic } from './sessionEventsDataLogic'
import { sessionRecordingMetaLogic } from './sessionRecordingMetaLogic'

describe('sessionEventsDataLogic', () => {
    let logic: ReturnType<typeof sessionEventsDataLogic.build>
    let metaLogic: ReturnType<typeof sessionRecordingMetaLogic.build>

    const emptyRelatedEventsResponse = {
        columns: recordingEventsJson.columns,
        hasMore: false,
        results: [],
        types: recordingEventsJson.types,
    }

    // Fails the first `failCount` query requests with `status`, then serves real event data.
    const failFirstQueries = (failCount: number, status: number): MockSignature => {
        let calls = 0
        return async (req): Promise<[number, any]> => {
            calls += 1
            if (calls <= failCount) {
                return [status, {}]
            }
            const body = await req.json()
            const query = body.query?.query || ''
            // The session query is keyed off `$session_id =`; everything else is the related-events query.
            return query.includes('$session_id =') ? [200, recordingEventsJson] : [200, emptyRelatedEventsResponse]
        }
    }

    const mountWith = (queryHandler: MockSignature): void => {
        setupSessionRecordingTest({ customQueryHandler: queryHandler })
        const props = { sessionRecordingId: '2', blobV2PollingDisabled: true }
        metaLogic = sessionRecordingMetaLogic(props)
        logic = sessionEventsDataLogic(props)
        metaLogic.mount()
        logic.mount()
        jest.spyOn(api, 'create')
    }

    it('retries once and recovers when the query endpoint returns a transient 503', async () => {
        // Fail both concurrent requests in the initial Promise.all so the retry path is exercised.
        mountWith(failFirstQueries(2, 503))

        await expectLogic(logic, () => {
            metaLogic.actions.loadRecordingMeta()
        })
            .toDispatchActions(['loadEvents', 'loadEventsSuccess'])
            .toNotHaveDispatchedActions(['loadEventsFailure'])

        expect(logic.values.sessionEventsData).toHaveLength(recordingEventsJson.results.length)
    })

    it('degrades to an empty events panel when the query endpoint keeps returning 503', async () => {
        mountWith(failFirstQueries(Infinity, 503))

        await expectLogic(logic, () => {
            metaLogic.actions.loadRecordingMeta()
        })
            .toDispatchActions(['loadEvents', 'loadEventsSuccess'])
            .toNotHaveDispatchedActions(['loadEventsFailure'])
            .toMatchValues({ sessionEventsData: [] })
    })

    it('re-throws non-transient errors so real bugs still surface', async () => {
        silenceKeaLoadersErrors()
        mountWith(failFirstQueries(Infinity, 400))

        await expectLogic(logic, () => {
            metaLogic.actions.loadRecordingMeta()
        }).toDispatchActions(['loadEvents', 'loadEventsFailure'])

        resumeKeaLoadersErrors()
    })
})
