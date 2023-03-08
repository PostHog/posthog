import { UUIDT } from '../src/utils/utils'
import { capture, createOrganization, createTeam, fetchEvents, fetchPerformanceEvents } from './api'
import { waitForExpect } from './expectations'

let organizationId: string

beforeAll(async () => {
    organizationId = await createOrganization()
})

test.concurrent(
    `peformance event ingestion: captured, processed, ingested`,
    async () => {
        const teamId = await createTeam(organizationId)
        const distinctId = new UUIDT().toString()
        const uuid = new UUIDT().toString()

        await capture({
            teamId,
            distinctId,
            uuid,
            event: '$performance_event',
            properties: {
                '0': 'resource',
                $session_id: '$session_id_1',
                $window_id: '$window_id_1',
                $pageview_id: '$pageview_id_1',
                $current_url: '$current_url_1',
            },
        })

        const perfEvents = await waitForExpect(async () => {
            const perfEvents = await fetchPerformanceEvents(teamId)
            expect(perfEvents.length).toBe(1)
            return perfEvents
        })
        const events = await fetchEvents(teamId)
        expect(events.length).toBe(0)

        expect(perfEvents.length).toBe(1)

        // processEvent did not modify
        expect(perfEvents[0]).toMatchObject({
            entry_type: 'resource',
            session_id: '$session_id_1',
            window_id: '$window_id_1',
            pageview_id: '$pageview_id_1',
            current_url: '$current_url_1',
        })
    },
    20000
)
