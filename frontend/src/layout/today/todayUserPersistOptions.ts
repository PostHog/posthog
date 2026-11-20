import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'

const TEAM_ID = getCurrentTeamIdOrNone()
const USER_ID = getCurrentUserIdOrNone()

/**
 * Kea persist options for state that belongs to one person in one project. Without both ids nothing persists, so one
 * account never sees another's.
 */
export const TODAY_USER_PERSIST_OPTIONS =
    TEAM_ID && USER_ID ? { persist: true, prefix: `${TEAM_ID}__${USER_ID}__` } : { persist: false }
