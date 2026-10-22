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
 * Runs a step that reads only the message. A throw counts as a parse error and returns null, so the
 * caller skips the message. A dependency lookup must not run inside `read`. Its error is not the
 * message's fault, so skipping the message would lose the event.
 */
export function readMessage<T>(errorLog: string, read: () => T, onError?: (error: string) => void): T | null {
    try {
        return read()
    } catch (e) {
        const error = e instanceof Error ? e.message : String(e)
        logger.error(errorLog, e)
        counterParseError.labels({ error }).inc()
        onError?.(error)
        return null
    }
}
