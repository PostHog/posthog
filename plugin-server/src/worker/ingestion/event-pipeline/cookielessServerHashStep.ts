import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
// @ts-expect-error no types
import * as siphashDouble from 'siphash/lib/siphash-double'
import { getDomain } from 'tldts'

import { ConcurrencyController } from '../../../utils/concurrencyController'
import { DB } from '../../../utils/db/db'
import { UUID7 } from '../../../utils/utils'
import { EventPipelineRunner } from './runner'

const TIMEZONE_FALLBACK = 'UTC'
const SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID = '$sentinel_cookieless_server_hash'

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

    const { userAgent, ip, host, timezone, timestampMs, teamId } = getProperties(event, timestamp)
    if (!userAgent || !ip || !host) {
        // TODO log
        return [undefined]
    }

    const hashValue = await doHash(runner.hub.db, timestampMs, timezone, teamId, ip, host, userAgent)
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

function getProperties(
    event: PluginEvent,
    timestamp: string
): {
    userAgent: string | undefined
    ip: string | undefined
    host: string | undefined
    timezone: string | undefined
    timestampMs: number
    teamId: number
} {
    const userAgent = event.properties?.['$raw_user_agent']
    const ip = event.properties?.['$ip']
    const host = event.properties?.['$host']
    const timezone = event.properties?.['$timezone'] || TIMEZONE_FALLBACK
    const timestampMs = DateTime.fromISO(timestamp).toMillis()
    const teamId = event.team_id

    return { userAgent, ip, host, timezone, timestampMs, teamId }
}

const localSaltMap: Record<string, Uint32Array> = {}
const mutex = new ConcurrencyController(1)

export async function getSaltForDay(db: DB, timestamp: number, timeZone: string): Promise<Uint32Array> {
    // get the day based on the timezone
    const parts = new Intl.DateTimeFormat('en', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(new Date(timestamp))
    const year = parts.find((part) => part.type === 'year')?.value
    const month = parts.find((part) => part.type === 'month')?.value
    const day = parts.find((part) => part.type === 'day')?.value
    const yyyymmdd = `${year}-${month}-${day}`

    // see if we have it locally
    if (localSaltMap[yyyymmdd]) {
        return localSaltMap[yyyymmdd]
    }

    // get the salt for the day from redis, but only do this once for this node process
    return mutex.run({
        fn: async (): Promise<Uint32Array> => {
            // check if we got the salt while waiting for the mutex
            if (localSaltMap[yyyymmdd]) {
                return localSaltMap[yyyymmdd]
            }

            // try to get it from redis instead
            const saltBase64 = await db.redisGet<string | null>(
                `cookieless_salt:${yyyymmdd}`,
                null,
                'cookielessServerHashStep'
            )
            if (saltBase64) {
                const salt = base64StringToUint32Array(saltBase64)
                localSaltMap[yyyymmdd] = salt
                return salt
            }

            // try to write a new one to redis, but don't overwrite
            const newSaltParts = createRandomUint32x4()
            const setResult = await db.redisSetNK(
                `cookieless_salt:${yyyymmdd}`,
                uint32ArrayToBase64String(newSaltParts),
                'cookielessServerHashStep',
                60 * 60 * 24 * 3
            )
            if (setResult === 'OK') {
                localSaltMap[yyyymmdd] = newSaltParts
                return newSaltParts
            }

            // if we couldn't write, it means that it exists in redis already
            const saltBase64Retry = await db.redisGet<string | null>(
                `cookieless_salt:${yyyymmdd}`,
                null,
                'cookielessServerHashStep'
            )
            if (!saltBase64Retry) {
                throw new Error('Failed to get salt from redis')
            }
            return base64StringToUint32Array(saltBase64Retry)
        },
        priority: timestamp,
    })
}

export function base64StringToUint32Array(base64: string): Uint32Array {
    return new Uint32Array(Buffer.from(base64, 'base64').buffer)
}
export function uint32ArrayToBase64String(uint32Array: Uint32Array): string {
    return Buffer.from(uint32Array.buffer).toString('base64')
}

export function createRandomUint32x4(): Uint32Array {
    const randomArray = new Uint32Array(4)
    crypto.getRandomValues(randomArray)
    return randomArray
}

export async function doHash(
    db: DB,
    timestamp: number,
    timezone: string,
    teamId: number,
    ip: string,
    host: string,
    userAgent: string
) {
    const salt = await getSaltForDay(db, timestamp, timezone)
    const rootDomain = getDomain(host) || host
    // use the 128-bit version of siphash to get the result, with a stripe-style prefix, so we can see what these ids are when debugging
    return 'cklsh_' + siphashDouble.hash_hex(salt, `${teamId.toString()}-${ip}-${rootDomain}-${userAgent}`)
}
