import * as jwt from 'jsonwebtoken'

import { EventHeaders, IncomingEventWithTeam, JwtVerificationStatus } from '../../types'
import { TeamSecretKeysManager } from '../../utils/team-secret-keys-manager'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

type JwtVerificationResult = {
    verified: JwtVerificationStatus
}

async function validateJwt(
    teamSecretKeysManager: TeamSecretKeysManager,
    headers: EventHeaders,
    eventWithTeam: IncomingEventWithTeam
): Promise<JwtVerificationResult> {
    if (!headers.jwt) {
        return { verified: JwtVerificationStatus.NotVerified }
    }

    try {
        const decoded = jwt.decode(headers.jwt, { complete: true })
        if (!decoded || typeof decoded === 'string') {
            return { verified: JwtVerificationStatus.Invalid }
        }

        const kid = decoded.header.kid
        if (!kid) {
            return { verified: JwtVerificationStatus.Invalid }
        }

        const secretKey = await teamSecretKeysManager.getSecretKey(kid)
        if (!secretKey) {
            return { verified: JwtVerificationStatus.Invalid }
        }

        if (secretKey.team_id !== eventWithTeam.team.id) {
            return { verified: JwtVerificationStatus.Invalid }
        }

        try {
            const verifiedPayload = jwt.verify(headers.jwt, secretKey.secure_value, {
                algorithms: ['HS256', 'HS512'],
            }) as any

            // JWT must contain distinct_id claim
            if (!verifiedPayload.distinct_id) {
                return { verified: JwtVerificationStatus.Invalid }
            }

            // Verify that the distinct_id in the JWT matches the event's distinct_id
            if (verifiedPayload.distinct_id !== eventWithTeam.event.distinct_id) {
                return { verified: JwtVerificationStatus.Invalid }
            }

            return { verified: JwtVerificationStatus.Verified }
        } catch (err) {
            return { verified: JwtVerificationStatus.Invalid }
        }
    } catch (err) {
        return { verified: JwtVerificationStatus.Invalid }
    }
}

export function createValidateJwtStep<T extends { headers: EventHeaders; eventWithTeam: IncomingEventWithTeam }>(
    teamSecretKeysManager: TeamSecretKeysManager
): ProcessingStep<T, T & { verified: JwtVerificationStatus }> {
    return async function validateJwtStep(input) {
        const { headers, eventWithTeam } = input

        const result = await validateJwt(teamSecretKeysManager, headers, eventWithTeam)

        // Check if the event should be rejected based on the team's verification mode
        const verifyEventsMode = eventWithTeam.team.verify_events || 'accept_all'

        if (verifyEventsMode === 'reject_invalid' && result.verified === JwtVerificationStatus.Invalid) {
            return drop('jwt_invalid')
        }

        if (verifyEventsMode === 'reject_unverified' && result.verified !== JwtVerificationStatus.Verified) {
            return drop('jwt_not_verified')
        }

        return ok({ ...input, verified: result.verified })
    }
}
