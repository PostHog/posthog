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

    it('hydrates phase 2 with uuid filter and a narrow time window derived from phase-1 timestamps', async () => {
        const phaseOneRows = [
            ['uuid-newest', '2024-06-09T12:00:05.000Z'],
            ['uuid-middle', '2024-06-09T12:00:03.000Z'],
            ['uuid-oldest', '2024-06-09T12:00:01.000Z'],
        ]
        const hydratedResponse = { results: [['event-row', 'person-row']] }

        mockedPerformQuery.mockResolvedValueOnce({ results: phaseOneRows }).mockResolvedValueOnce(hydratedResponse)

        const result = await performWideEventsQueryInTwoPhases(intent)

        expect(mockedPerformQuery).toHaveBeenCalledTimes(2)
        const phaseTwo = mockedPerformQuery.mock.calls[1][0] as EventsQuery

        // Phase 2 keeps the original wide select so the caller still gets the hydrated columns.
        expect(phaseTwo.select).toEqual(intent.select)

        // Phase 2 appends an extra fixedProperties group with `uuid IN [...]` and keeps the original filter.
        expect(phaseTwo.fixedProperties).toHaveLength((intent.fixedProperties?.length ?? 0) + 1)
        const uuidFilterGroup = phaseTwo.fixedProperties![phaseTwo.fixedProperties!.length - 1]
        expect(uuidFilterGroup).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.HogQL,
                    key: expect.stringMatching(/uuid IN \['uuid-newest', 'uuid-middle', 'uuid-oldest'\]/),
                },
            ],
        })

        // Phase 2 window is bounded by the oldest/newest phase-1 timestamps with a 1-second pad on each side.
        expect(phaseTwo.after).toBe('2024-06-09T12:00:00.000Z')
        expect(phaseTwo.before).toBe('2024-06-09T12:00:06.000Z')

        // Phase 2 limit matches the candidate count so we never re-widen the result.
        expect(phaseTwo.limit).toBe(phaseOneRows.length)

        expect(result).toBe(hydratedResponse)
    })

    it('passes through additional fields on the intent query (filterTestAccounts, properties, where)', async () => {
        const intentWithExtras: EventsQuery = {
            ...intent,
            filterTestAccounts: true,
            where: ['team_id = 1'],
            properties: [{ type: PropertyFilterType.HogQL, key: "properties.foo = 'bar'" }],
        }
        mockedPerformQuery
            .mockResolvedValueOnce({ results: [['uuid-a', '2024-06-09T12:00:00.000Z']] })
            .mockResolvedValueOnce({ results: [] })

        await performWideEventsQueryInTwoPhases(intentWithExtras)

        const phaseOne = mockedPerformQuery.mock.calls[0][0] as EventsQuery
        const phaseTwo = mockedPerformQuery.mock.calls[1][0] as EventsQuery

        expect(phaseOne.filterTestAccounts).toBe(true)
        expect(phaseOne.where).toEqual(['team_id = 1'])
        expect(phaseOne.properties).toEqual(intentWithExtras.properties)
        expect(phaseTwo.filterTestAccounts).toBe(true)
        expect(phaseTwo.where).toEqual(['team_id = 1'])
        expect(phaseTwo.properties).toEqual(intentWithExtras.properties)
    })

    it('handles single-result phase 1 by collapsing the window to one timestamp ± 1s', async () => {
        mockedPerformQuery
            .mockResolvedValueOnce({ results: [['uuid-solo', '2024-06-09T12:00:05.000Z']] })
            .mockResolvedValueOnce({ results: [['hydrated']] })

        await performWideEventsQueryInTwoPhases(intent)

        const phaseTwo = mockedPerformQuery.mock.calls[1][0] as EventsQuery
        expect(phaseTwo.after).toBe('2024-06-09T12:00:04.000Z')
        expect(phaseTwo.before).toBe('2024-06-09T12:00:06.000Z')
        expect(phaseTwo.limit).toBe(1)
    })

    it('does not mutate the intent query', async () => {
        const intentCopy = JSON.parse(JSON.stringify(intent))
        mockedPerformQuery
            .mockResolvedValueOnce({ results: [['uuid-a', '2024-06-09T12:00:00.000Z']] })
            .mockResolvedValueOnce({ results: [] })

        await performWideEventsQueryInTwoPhases(intent)

        expect(intent).toEqual(intentCopy)
    })
})
