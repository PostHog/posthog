import { performQuery } from '~/queries/query'
import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType } from '~/types'

import { performWideEventsQueryInTwoPhases } from './sampleEventsQuery'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const mockedPerformQuery = performQuery as jest.MockedFunction<typeof performQuery>

const intent: EventsQuery = {
    kind: NodeKind.EventsQuery,
    select: ['*', 'person', 'tuple(organization.created_at, organization.index, organization.key)'],
    fixedProperties: [
        {
            type: FilterLogicalOperator.And,
            values: [{ type: PropertyFilterType.HogQL, key: "event = '$pageview'" }],
        },
    ],
    after: '-7d',
    limit: 10,
    orderBy: ['timestamp DESC'],
    modifiers: { personsOnEventsMode: 'person_id_no_override_properties_on_events' },
}

describe('performWideEventsQueryInTwoPhases', () => {
    beforeEach(() => {
        mockedPerformQuery.mockReset()
    })

    it('strips wide select in phase 1 while preserving filters, window, order, limit', async () => {
        mockedPerformQuery.mockResolvedValueOnce({ results: [] })

        await performWideEventsQueryInTwoPhases(intent)

        expect(mockedPerformQuery).toHaveBeenCalledTimes(1)
        const phaseOne = mockedPerformQuery.mock.calls[0][0] as EventsQuery
        expect(phaseOne.select).toEqual(['uuid', 'timestamp'])
        expect(phaseOne.fixedProperties).toEqual(intent.fixedProperties)
        expect(phaseOne.after).toBe('-7d')
        expect(phaseOne.limit).toBe(10)
        expect(phaseOne.orderBy).toEqual(['timestamp DESC'])
        expect(phaseOne.modifiers).toEqual(intent.modifiers)
    })

    it('returns the phase-1 response without running phase 2 when nothing matches', async () => {
        const emptyResponse = { results: [], columns: [], types: [], hogql: 'SELECT' }
        mockedPerformQuery.mockResolvedValueOnce(emptyResponse)

        const result = await performWideEventsQueryInTwoPhases(intent)

        expect(mockedPerformQuery).toHaveBeenCalledTimes(1)
        expect(result).toBe(emptyResponse)
    })

    it('hydrates phase 2 by exact (uuid, timestamp) tuples, drops the original filter, and bounds the window', async () => {
        const phaseOneRows = [
            ['019eacd8-2ab7-76b0-8e40-604d7f8e6961', '2026-06-09T07:45:08.404000-07:00'],
            ['019eaca0-c933-7806-9aab-e211b2cdf59b', '2026-06-09T06:44:38.960000-07:00'],
            ['019e8f53-c8b8-748d-8619-f4ffb26e8e93', '2026-06-03T14:11:33.301000-07:00'],
        ]
        const hydratedResponse = { results: [['event-row', 'person-row']] }

        mockedPerformQuery.mockResolvedValueOnce({ results: phaseOneRows }).mockResolvedValueOnce(hydratedResponse)

        const result = await performWideEventsQueryInTwoPhases(intent)

        expect(mockedPerformQuery).toHaveBeenCalledTimes(2)
        const phaseTwo = mockedPerformQuery.mock.calls[1][0] as EventsQuery

        // Phase 2 keeps the original wide select so the caller still gets the hydrated columns.
        expect(phaseTwo.select).toEqual(intent.select)

        // Phase 2 drops the original filter — phase 1 already certified those UUIDs.
        expect(phaseTwo.fixedProperties).toBeUndefined()
        expect(phaseTwo.properties).toBeUndefined()

        // Phase 2 hydrates by exact (uuid, timestamp) tuples for primary-key granule pruning.
        // Timestamps are converted to UTC microsecond precision so the equality match is exact.
        expect(phaseTwo.where).toHaveLength(1)
        const whereFragment = phaseTwo.where![0]
        expect(whereFragment).toContain('(uuid, timestamp) IN (')
        expect(whereFragment).toContain("'019eacd8-2ab7-76b0-8e40-604d7f8e6961'")
        expect(whereFragment).toContain("'019eaca0-c933-7806-9aab-e211b2cdf59b'")
        expect(whereFragment).toContain("'019e8f53-c8b8-748d-8619-f4ffb26e8e93'")
        expect(whereFragment).toContain("toDateTime64('2026-06-09 14:45:08.404000', 6, 'UTC')")
        expect(whereFragment).toContain("toDateTime64('2026-06-09 13:44:38.960000', 6, 'UTC')")
        expect(whereFragment).toContain("toDateTime64('2026-06-03 21:11:33.301000', 6, 'UTC')")

        // Phase 2 window is bounded by the oldest/newest phase-1 timestamps with a 1-second pad
        // on each side as a belt-and-suspenders narrowing for granule pruning.
        expect(phaseTwo.after).toBe('2026-06-03T21:11:32.301Z')
        expect(phaseTwo.before).toBe('2026-06-09T14:45:09.404Z')

        // Phase 2 limit matches the candidate count so we never re-widen the result.
        expect(phaseTwo.limit).toBe(phaseOneRows.length)

        expect(result).toBe(hydratedResponse)
    })

    it('preserves caller-supplied `where` fragments in phase 2 and appends the tuple filter', async () => {
        const intentWithWhere: EventsQuery = {
            ...intent,
            where: ['team_id = 1'],
        }
        mockedPerformQuery
            .mockResolvedValueOnce({
                results: [['019eacd8-2ab7-76b0-8e40-604d7f8e6961', '2026-06-09T07:45:08.404000-07:00']],
            })
            .mockResolvedValueOnce({ results: [] })

        await performWideEventsQueryInTwoPhases(intentWithWhere)

        const phaseOne = mockedPerformQuery.mock.calls[0][0] as EventsQuery
        const phaseTwo = mockedPerformQuery.mock.calls[1][0] as EventsQuery

        // Phase 1 keeps the original where (alongside the original filter) for correctness.
        expect(phaseOne.where).toEqual(['team_id = 1'])

        // Phase 2 keeps the caller's where and appends the tuple filter at the end.
        expect(phaseTwo.where).toHaveLength(2)
        expect(phaseTwo.where![0]).toBe('team_id = 1')
        expect(phaseTwo.where![1]).toContain('(uuid, timestamp) IN (')
    })

    it('handles single-result phase 1 by collapsing the window to one timestamp ± 1s', async () => {
        mockedPerformQuery
            .mockResolvedValueOnce({
                results: [['019eacd8-2ab7-76b0-8e40-604d7f8e6961', '2026-06-09T12:00:05.000000Z']],
            })
            .mockResolvedValueOnce({ results: [['hydrated']] })

        await performWideEventsQueryInTwoPhases(intent)

        const phaseTwo = mockedPerformQuery.mock.calls[1][0] as EventsQuery
        expect(phaseTwo.after).toBe('2026-06-09T12:00:04.000Z')
        expect(phaseTwo.before).toBe('2026-06-09T12:00:06.000Z')
        expect(phaseTwo.limit).toBe(1)
    })

    it('does not mutate the intent query', async () => {
        const intentCopy = JSON.parse(JSON.stringify(intent))
        mockedPerformQuery
            .mockResolvedValueOnce({
                results: [['019eacd8-2ab7-76b0-8e40-604d7f8e6961', '2026-06-09T12:00:00.000000Z']],
            })
            .mockResolvedValueOnce({ results: [] })

        await performWideEventsQueryInTwoPhases(intent)

        expect(intent).toEqual(intentCopy)
    })
})
