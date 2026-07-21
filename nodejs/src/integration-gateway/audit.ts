import { logger } from '~/common/utils/logger'

/**
 * One credential-fetch audit record, emitted for every successful request. Records who fetched
 * which integration ids and the resolution outcome — but NEVER any credential value. This is the
 * durable-in-logs "who accessed which credential, when, on whose behalf" trail.
 */
export interface AuditEvent {
    caller: string
    teamId: number
    requested: number[]
    resolved: number[]
    cacheHits: number
    dbLoaded: number
    requestId: string
}

export function emitAudit(event: AuditEvent): void {
    logger.info('🔑', 'integration_gateway.audit credential_fetch', {
        caller: event.caller,
        team_id: event.teamId,
        requested: event.requested,
        resolved: event.resolved,
        cache_hits: event.cacheHits,
        db_loaded: event.dbLoaded,
        request_id: event.requestId,
    })
}
