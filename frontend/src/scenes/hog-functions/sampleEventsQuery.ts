import { dayjs } from 'lib/dayjs'

import { performQuery } from '~/queries/query'
import { EventsQuery, EventsQueryResponse } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { FilterLogicalOperator, PropertyFilterType } from '~/types'

// Run an EventsQuery in two phases to avoid reading wide columns (`properties`, `elements_chain`,
// `person_properties`, `groupN_properties`) for every row ClickHouse must scan to satisfy the filter.
// Phase 1 scans only `uuid, timestamp` with the original filter + window + order + limit. Phase 2
// re-issues the wide query constrained to those UUIDs and the narrow time window they landed in,
// so the wide-column read only happens for the rows we keep.
//
// Filter evaluation cost is unchanged — both phases evaluate the same WHERE clause. The win is on
// per-scanned-row projection cost during deep scans for sparse filters. See sessionEventsDataLogic
// for the same window-bounded `uuid IN (...)` pattern applied elsewhere.
export async function performWideEventsQueryInTwoPhases(intent: EventsQuery): Promise<EventsQueryResponse> {
    const phaseOne: EventsQuery = {
        ...intent,
        select: ['uuid', 'timestamp'],
    }
    const phaseOneResponse = await performQuery(phaseOne)
    const phaseOneResults = phaseOneResponse.results as Array<[string, string]>
    if (phaseOneResults.length === 0) {
        return phaseOneResponse
    }

    const uuids = phaseOneResults.map((r) => r[0])
    const timestampsMs = phaseOneResults.map((r) => dayjs(r[1]).valueOf())
    const after = dayjs(Math.min(...timestampsMs))
        .subtract(1, 'second')
        .toISOString()
    const before = dayjs(Math.max(...timestampsMs))
        .add(1, 'second')
        .toISOString()

    const phaseTwo: EventsQuery = {
        ...intent,
        fixedProperties: [
            ...(intent.fixedProperties ?? []),
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: PropertyFilterType.HogQL,
                        key: hogql`uuid IN ${uuids}`,
                    },
                ],
            },
        ],
        after,
        before,
        limit: uuids.length,
    }

    return await performQuery(phaseTwo)
}
