import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
// @ts-expect-error no types
import * as siphashDouble from 'siphash/lib/siphash-double'
import { getDomain } from 'tldts'

import { UUID7 } from '../../../utils/utils'
import { EventPipelineRunner } from './runner'

const TIMEZONE_FALLBACK = 'UTC'
const SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID = '$sentinel_cookieless_server_hash'

export function getSaltForDay(timestamp: number, timezone: string | undefined): string {
    // get the day based on the timezone
    const datetime = new Date(timestamp)
    // use the esperanto locale code to get the day of this timestamp in the timezone in YYYY-MM-DD format
    const day = datetime.toLocaleDateString('eo', { timeZone: timezone || TIMEZONE_FALLBACK })
    const dayParts = day.split('-')

    // lookup the salt for this day
    // TODO
    return dayParts[0] + dayParts[1] + dayParts[2] + '00000000'
}

export function doHash(
    timestamp: number,
    timezone: string | undefined,
    teamId: number,
    ip: string,
    host: string,
    userAgent: string
) {
    const salt = getSaltForDay(timestamp, timezone)
    const key = siphashDouble.string16_to_key(salt)
    const rootDomain = getDomain(host) || host
    // use the 128-bit version of siphash to get the result, with a stripe-style prefix so we can see what these ids are when debugging
    return 'cklsh_' + siphashDouble.hash_hex(key, `${teamId.toString()}-${ip}-${rootDomain}-${userAgent}`)
}

export async function cookielessServerHashStep(
    runner: EventPipelineRunner,
    event: PluginEvent
): Promise<[PluginEvent | undefined]> {
    // if events aren't using this mode, skip all processing
    if (event.properties?.['$device_id'] !== SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID) {
        return [event]
    }
    // if the team isn't using this mode, skip all processing
    // const team = await runner.hub.teamManager.getTeamForEvent(event)
    // if (!team?.cookieless_server_hash_opt_in) {
    //     // TODO log
    //     return [event]
    // }

    const timestamp = event.timestamp ?? event.sent_at ?? event.now

    // drop some events that aren't valid in this mode
    if (!timestamp) {
        // TODO log
        return [undefined]
    }
    const sessionId = event.properties['$session_id']
    if (sessionId !== SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID) {
        // TODO log
        return [undefined]
    }
    // if it's an identify event, it must have the sentinel distinct id
    if (
        event.event === '$identify' &&
        event.properties['$anon_distinct_id'] !== SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID
    ) {
        // TODO log
        return [undefined]
    }

    // drop events that don't have the necessary properties
    const userAgent = event.properties['$raw_user_agent']
    const ip = event.properties['$ip']
    const host = event.properties['$host']
    const timezone = event.properties['$timezone']
    const timestampMs = DateTime.fromISO(timestamp).toMillis()
    const teamId = event.team_id
    if (!userAgent || !ip || !host) {
        // TODO log
        return [undefined]
    }

    const hashValue = doHash(timestampMs, timezone, teamId, ip, host, userAgent)
    event.properties['$device_id'] = hashValue

    // TRICKY: if a user were to log in and out, to avoid collisions, we would want a different hash value, so we store the set of identify event uuids for identifies
    // ASSUMPTION: all events are processed in order, and are processed exactly once
    const identifiesRedisKey = `cookieless_i:${hashValue}`
    // how many identifies have happened with that hash value?
    const numIdentifies = await runner.hub.db.redisSCard(identifiesRedisKey)
    // rehash with the number of identifies, so that each 'user' has a unique hash value
    const hashValue2 = numIdentifies === 0 ? hashValue : hashValue + '_' + numIdentifies

    if (event.event === '$identify') {
        // identify event, so the anon_distinct_id must be the sentinel and needs to be replaced

        // add this identify event id to redis
        await runner.hub.db.redisSAdd(identifiesRedisKey, event.uuid)
        await runner.hub.db.redisExpire(identifiesRedisKey, 60 * 60 * 24) // 24 hours // TODO this is the max but could be less, given we looked at the timestamp 10 lines of code ago

        // set the distinct id to the new hash value
        event.properties[`$anon_distinct_id`] = hashValue2
    } else if (event.distinct_id === SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID) {
        // event before identify has been called, distinct id is the sentinel and needs to be replaced
        event.distinct_id = hashValue2
        event.properties[`$distinct_id`] = hashValue2
    }

    const sessionRedisKey = `cookieless_s:${hashValue2}`
    // do we have a session id for this user already?
    let sessionInfo = await runner.hub.db.redisGet<{ s: string; t: number } | null>(
        sessionRedisKey,
        null,
        'cookielessServerHashStep',
        {
            jsonSerialize: true,
        }
    )
    // if not, or the TTL has expired, create a new one. Don't rely on redis TTL, as ingestion lag could approach the 30-minute session inactivity timeout
    if (!sessionInfo || timestampMs - sessionInfo.t > 60 * 30 * 1000) {
        const sessionId = new UUID7(timestampMs).toString()
        sessionInfo = { s: sessionId, t: timestampMs }
        await runner.hub.db.redisSet(sessionRedisKey, sessionInfo, 'cookielessServerHashStep', 60 * 60 * 24)
    } else {
        // otherwise, update the timestamp
        await runner.hub.db.redisSet(
            sessionRedisKey,
            { s: sessionInfo.s, t: timestampMs },
            'cookielessServerHashStep',
            60 * 60 * 24
        )
    }

    event.properties['$session_id'] = sessionInfo.s

    return [event]
}
