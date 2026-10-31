import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { isValidTeamId } from '~/common/utils/team-manager'

import { Team } from '../../types'
import { HogFunctionInvocationGlobals } from '../types'
import { counterParseError } from './metrics'

// The loaders batch team ids from many messages into one query. One invalid id fails that query for
// every message in it, on every read.
export function assertTeamId<T extends { team_id: unknown }>(message: T): T {
    if (!isValidTeamId(message.team_id)) {
        throw new Error('invalid_team_id')
    }
    return message
}

function errorMessage(e: unknown): string {
    return e instanceof Error ? e.message : String(e)
}

/**
 * If the step throws, this logs the error and counts it as a parse error. It then returns null, and
 * the caller skips the message. Wrap only a step that reads the message. A dependency lookup must not
 * run inside `step`. Its error is not the message's fault, so skipping the message would lose the event.
 */
export function skipIfMalformed<T>(errorLog: string, step: () => T, onError?: (error: string) => void): T | null {
    try {
        return step()
    } catch (e) {
        const error = errorMessage(e)
        logger.error(errorLog, e)
        counterParseError.labels({ error }).inc()
        onError?.(error)
        return null
    }
}

// What a parse step reads from one message: the team to look up, and how to build the globals once
// the team has loaded.
type ParsedMessage<TLoaded> = {
    teamId: unknown
    toGlobals: (loaded: TLoaded) => HogFunctionInvocationGlobals
}

export type ParseBatchOptions<TLoaded = Team> = {
    errorLog: string
    /** Reads only the message. Returns null to skip it. */
    parse: (message: Message) => ParsedMessage<TLoaded> | null
    /** Returns the team, or the team with what the consumer loads alongside it. Returns null to skip the message. */
    loadTeam: (teamId: number) => Promise<TLoaded | null>
    /** Skips a message whose team id is invalid. Without it, an invalid team id counts as a parse error. */
    onInvalidTeamId?: () => void
    /** Runs on each parse error. */
    onError?: (message: Message, error: string) => void
    /**
     * Keeps a message whose lookup failed with an error that is not retriable. Returns true when it kept
     * the message, so the batch skips it. Without it, or when it returns false, the error fails the batch.
     */
    parkLookupError?: (message: Message, error: string) => boolean
}

/**
 * Builds the globals for each message in a batch, in message order.
 *
 * `parse` and `toGlobals` do no I/O. They read only the message and the loaded team, so an error there
 * means the message is malformed. It fails the same way every time it is read, so this skips it. This
 * also skips a team id that `loadTeam` cannot query, for the reason `assertTeamId` gives.
 *
 * `loadTeam` reads Postgres. A retriable error from it fails the batch, so the consumer does not store
 * the batch's offsets and reads the batch again after the pod restarts. Skipping the message instead
 * would lose the event. Any other lookup error fails the batch too, unless `parkLookupError` keeps the
 * message.
 */
export async function parseBatch<TLoaded = Team>(
    messages: Message[],
    { errorLog, parse, loadTeam, onInvalidTeamId, onError, parkLookupError }: ParseBatchOptions<TLoaded>
): Promise<HogFunctionInvocationGlobals[]> {
    const results = await Promise.all(
        messages.map(async (message) => {
            const reportError = onError && ((error: string) => onError(message, error))
            const parsed = skipIfMalformed(
                errorLog,
                () => {
                    const parsed = parse(message)
                    if (!parsed) {
                        return null
                    }
                    const { teamId, toGlobals } = parsed
                    if (isValidTeamId(teamId)) {
                        return { teamId, toGlobals }
                    }
                    if (!onInvalidTeamId) {
                        throw new Error('invalid_team_id')
                    }
                    onInvalidTeamId()
                    return null
                },
                reportError
            )
            if (!parsed) {
                return null
            }
            const loaded = await loadTeam(parsed.teamId).catch((e) => {
                if (e?.isRetriable === true || !parkLookupError?.(message, errorMessage(e))) {
                    throw e
                }
                logger.error('Error looking up team data', e)
                return null
            })
            if (!loaded) {
                return null
            }
            return skipIfMalformed(errorLog, () => parsed.toGlobals(loaded), reportError)
        })
    )
    return results.filter((globals): globals is HogFunctionInvocationGlobals => globals !== null)
}
