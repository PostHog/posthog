import * as jwt from 'jsonwebtoken'

import { EventHeaders, IncomingEventWithTeam, JwtVerificationStatus } from '../../types'
import { logger } from '../../utils/logger'
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
            logger.warn('Failed to decode JWT header')
            return { verified: JwtVerificationStatus.Invalid }
        }

        const kid = decoded.header.kid
        if (!kid) {
            logger.warn('JWT missing kid claim in header')
            return { verified: JwtVerificationStatus.Invalid }
        }

        const secretKey = await teamSecretKeysManager.getSecretKey(kid)
        if (!secretKey) {
            logger.warn(`Secret key not found for kid: ${kid}`)
            return { verified: JwtVerificationStatus.Invalid }
        }

        if (secretKey.team_id !== eventWithTeam.team.id) {
            logger.warn(
                `Secret key team mismatch: key belongs to team ${secretKey.team_id}, event belongs to team ${eventWithTeam.team.id}`
            )
            return { verified: JwtVerificationStatus.Invalid }
        }

        try {
            jwt.verify(headers.jwt, secretKey.secure_value, {
                algorithms: ['HS256', 'HS512'],
            })

            return { verified: JwtVerificationStatus.Verified }
        } catch (err) {
            logger.warn(`JWT verification failed: ${err}`)
            return { verified: JwtVerificationStatus.Invalid }
        }
    } catch (err) {
        logger.error(`Error validating JWT: ${err}`)
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
            logger.info(
                `Dropping event with invalid JWT for team ${eventWithTeam.team.id} (verify_events: reject_invalid)`
            )
            return drop('jwt_invalid')
        }

        if (verifyEventsMode === 'reject_unverified' && result.verified !== JwtVerificationStatus.Verified) {
            logger.info(
                `Dropping unverified event for team ${eventWithTeam.team.id} (verify_events: reject_unverified, status: ${result.verified})`
            )
            return drop('jwt_not_verified')
        }

        return ok({ ...input, verified: result.verified })
    }
}
