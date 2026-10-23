import { logger } from '~/common/utils/logger'
import { isValidTeamId } from '~/common/utils/team-manager'

import { counterParseError } from './metrics'

// The loaders batch team ids from many messages into one query. One invalid id fails that query for
// every message in it, on every read.
export function assertTeamId<T extends { team_id: unknown }>(message: T): T {
    if (!isValidTeamId(message.team_id)) {
        throw new Error('invalid_team_id')
    }
    return message
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
        const error = e instanceof Error ? e.message : String(e)
        logger.error(errorLog, e)
        counterParseError.labels({ error }).inc()
        onError?.(error)
        return null
    }
}
