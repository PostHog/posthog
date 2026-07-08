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
// `properties` for filter evaluation across the same granule set — and now also project the wide
// JSON columns on top, which is what trips the per-query memory limit. The tuple constraint lets
// the primary-key sparse index over `(team_id, toDate(timestamp), event, ...)` prune to just the
// granules holding those rows.
//
// On top of that, when the caller's window is wider than 24h we try a 24h pre-stage first. Most
// matching events the user wants to test against fire recently, so this skips the deep scan when
// possible. If the 24h pre-stage returns nothing we fall through to the caller's original window.
export async function performWideEventsQueryInTwoPhases(intent: EventsQuery): Promise<EventsQueryResponse> {
    if (shouldTry24hPreStage(intent.after)) {
        const preResponse = await runTwoPhase({ ...intent, after: '-24h' })
        if ((preResponse.results as unknown[]).length > 0) {
            return preResponse
        }
    }
    return await runTwoPhase(intent)
}

async function runTwoPhase(intent: EventsQuery): Promise<EventsQueryResponse> {
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

// dayjs only has millisecond precision, so lift the microseconds straight from the source string
// and reattach them after converting the base to UTC.
function formatClickHouseUtcDateTime64(timestamp: string): string {
    const microsMatch = timestamp.match(/\.(\d{1,6})/)
    const micros = (microsMatch?.[1] ?? '').padEnd(6, '0')
    const base = dayjs(timestamp).utc().format('YYYY-MM-DD HH:mm:ss')
    return `toDateTime64('${base}.${micros}', 6, 'UTC')`
}

// Returns true if `after` represents a window strictly wider than 24h. Accepts the relative range
// shorthand the testing flows use (`-7d`, `-30d`, `-24h`, `-1h`, etc.) and absolute ISO timestamps.
// If the window is 24h or narrower we skip the pre-stage so we never widen a caller's request.
function shouldTry24hPreStage(after: string | undefined): boolean {
    if (!after) {
        return false
    }
    const relativeMatch = after.match(/^-(\d+)([smhdwMy])$/)
    if (relativeMatch) {
        const value = parseInt(relativeMatch[1], 10)
        const unit = relativeMatch[2] as 's' | 'm' | 'h' | 'd' | 'w' | 'M' | 'y'
        return dayjs.duration(value, unit).asHours() > 24
    }
    const parsed = dayjs(after)
    if (parsed.isValid()) {
        return dayjs().diff(parsed, 'hour', true) > 24
    }
    return false
}
