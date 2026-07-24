import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { eventDroppedCounter } from '~/common/metrics'
import { TeamManager } from '~/common/utils/team-manager'
import { tokenOrTeamPresentCounter } from '~/ingestion/common/metrics'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, IncomingEvent, Team } from '~/types'

export interface ResolveTeamStepInput {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
}

type ResolveTeamError = { error: true; cause: 'no_token' | 'invalid_token' }
type ResolveTeamSuccess = { error: false; team: Team }
type ResolveTeamResult = ResolveTeamSuccess | ResolveTeamError

export const verifiedPropertyCounter = new Counter({
    name: 'ingestion_verified_property_total',
    help: 'Events marked $verified (captured with the secret API token) or with a client-supplied $verified stripped',
    labelNames: ['action'],
})

// $set/$set_once carry properties onto the person; $unset removes them. A client could
// smuggle a forged $verified person property through any of these, so they are scrubbed
// alongside the top-level property on non-secret-token events.
const PERSON_PROPERTY_OPERATIONS = ['$set', '$set_once', '$unset'] as const

function stripForgedVerified(properties: Record<string, any>): boolean {
    let stripped = false

    if ('$verified' in properties) {
        delete properties['$verified']
        stripped = true
    }

    for (const operation of PERSON_PROPERTY_OPERATIONS) {
        const container = properties[operation]
        if (Array.isArray(container)) {
            // $unset is conventionally a list of property names to remove.
            const filtered = container.filter((name) => name !== '$verified')
            if (filtered.length !== container.length) {
                properties[operation] = filtered
                stripped = true
            }
        } else if (container && typeof container === 'object' && '$verified' in container) {
            delete container['$verified']
            stripped = true
        }
    }

    return stripped
}

/**
 * $verified is a server-controlled property: it is set when the event was captured with
 * the team's secret API token (primary or backup, so token rotation keeps verifying),
 * and any client-supplied value is stripped otherwise. Stripping also covers $verified
 * smuggled through $set/$set_once/$unset, which would otherwise forge a "Verified"
 * person property without the secret token.
 */
export function applyVerifiedProperty(event: PluginEvent, token: string | undefined, team: Team): void {
    const sentWithSecretToken =
        token !== undefined && (token === team.secret_api_token || token === team.secret_api_token_backup)

    if (sentWithSecretToken) {
        event.properties = { ...(event.properties ?? {}), $verified: true }
        verifiedPropertyCounter.labels({ action: 'verified' }).inc()
    } else if (event.properties && stripForgedVerified(event.properties)) {
        verifiedPropertyCounter.labels({ action: 'stripped' }).inc()
    }
}

async function resolveTeam(
    teamManager: TeamManager,
    token: string | undefined,
    teamId: number | null | undefined
): Promise<ResolveTeamResult> {
    tokenOrTeamPresentCounter
        .labels({
            team_id_present: teamId ? 'true' : 'false',
            token_present: token ? 'true' : 'false',
        })
        .inc()

    // Events with no token are dropped, they should be blocked by capture
    if (!token) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        return { error: true, cause: 'no_token' }
    }

    const team = await teamManager.getTeamByToken(token)
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        return { error: true, cause: 'invalid_token' }
    }

    return { error: false, team }
}

export function createResolveTeamStep<TInput extends ResolveTeamStepInput>(
    teamManager: TeamManager
): ProcessingStep<TInput, Omit<TInput, 'event'> & { event: PluginEvent; team: Team }> {
    return async function resolveTeamStep(input) {
        const { event: incomingEvent, ...restInput } = input

        const result = await resolveTeam(teamManager, input.headers.token, incomingEvent.event.team_id)

        if (result.error) {
            return drop(result.cause)
        }

        const pluginEvent: PluginEvent = { ...incomingEvent.event, team_id: result.team.id }
        applyVerifiedProperty(pluginEvent, input.headers.token, result.team)
        return ok({ ...restInput, event: pluginEvent, team: result.team })
    }
}
