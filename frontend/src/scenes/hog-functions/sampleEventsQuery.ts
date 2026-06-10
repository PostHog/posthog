import { dayjs } from 'lib/dayjs'

import { performQuery } from '~/queries/query'
import { EventsQuery, EventsQueryResponse } from '~/queries/schema/schema-general'

// Two-phase EventsQuery to keep memory bounded on high-volume teams.
//
// Phase 1 keeps the original filter but projects only `uuid, timestamp` — wide JSON columns
// (`properties`, `person_properties`, `groupN_properties`, `elements_chain`) aren't decompressed.
//
// Phase 2 hydrates by exact `(uuid, timestamp)` tuples and drops the original filter. Phase 1
// already certified the matches, so re-applying the filter would force ClickHouse to re-read
// `properties` for filter evaluation across the same granule set — defeating the optimization
// and reproducing the original OOM. The tuple filter lets the primary-key sparse index prune to
// just the granules holding those rows, so wide-column reads stay bounded.
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

    const timestampsMs = phaseOneResults.map(([, t]) => dayjs(t).valueOf())
    const after = dayjs(Math.min(...timestampsMs))
        .subtract(1, 'second')
        .toISOString()
    const before = dayjs(Math.max(...timestampsMs))
        .add(1, 'second')
        .toISOString()

    const tupleList = phaseOneResults.map(([u, t]) => `('${u}', ${formatClickHouseUtcDateTime64(t)})`).join(', ')

    const phaseTwo: EventsQuery = {
        ...intent,
        fixedProperties: undefined,
        properties: undefined,
        where: [...(intent.where ?? []), `(uuid, timestamp) IN (${tupleList})`],
        after,
        before,
        limit: phaseOneResults.length,
    }

    return await performQuery(phaseTwo)
}

// dayjs only has millisecond precision, so we lift microseconds straight from the source string
// and reattach them after converting the base to UTC.
function formatClickHouseUtcDateTime64(timestamp: string): string {
    const microsMatch = timestamp.match(/\.(\d{1,6})/)
    const micros = (microsMatch?.[1] ?? '').padEnd(6, '0')
    const base = dayjs(timestamp).utc().format('YYYY-MM-DD HH:mm:ss')
    return `toDateTime64('${base}.${micros}', 6, 'UTC')`
}
