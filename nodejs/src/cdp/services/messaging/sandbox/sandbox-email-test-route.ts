import { randomUUID } from 'crypto'
import express from 'ultimate-express'
import { z } from 'zod'

import { logger } from '~/common/utils/logger'

import { ScopedServiceJwt } from '../../../utils/scoped-service-jwt'
import { SandboxEmailStepResult } from '../../hogflows/actions/email_sandbox'
import { SandboxEmailEvents } from './sandbox-email-events'
import { SEND_RATE_LIMITED, SandboxEmailService, SandboxSendOutcome } from './sandbox-email.service'
import { SandboxSesBucket, claimSesSlot } from './sandbox-ses-bucket'

export const SANDBOX_TEST_SEND_PATH = '/api/projects/:team_id/sandbox_email/test_send'

const TestSendRequestSchema = z.object({
    hog_flow_id: z.string().regex(/^[A-Za-z0-9_-]{1,64}$/),
    action_id: z.string().regex(/^[A-Za-z0-9_-]{1,128}$/),
    email: z.unknown(),
    message_category_id: z.string().optional(),
    message_category_type: z.enum(['marketing', 'transactional']).optional(),
    email_sending_paused: z.boolean().optional(),
})

export type SandboxEmailTestRouteDeps = {
    jwt: Pick<ScopedServiceJwt, 'enabled' | 'verify'>
    service: Pick<SandboxEmailService, 'send'> | null
    events: Pick<SandboxEmailEvents, 'capture'>
    sesBucket: SandboxSesBucket | null
}

export function sandboxEmailTestRouter(deps: SandboxEmailTestRouteDeps): express.Router {
    const router = express.Router()
    router.post(SANDBOX_TEST_SEND_PATH, (req, res) => {
        handleTestSend(deps, req, res).catch((error) => {
            logger.error('Sandbox email test send failed', { error: String(error) })
            res.status(500).json({ error: 'Sandbox email test send failed' })
        })
    })
    return router
}

async function handleTestSend(
    { jwt, service, events, sesBucket }: SandboxEmailTestRouteDeps,
    req: express.Request,
    res: express.Response
): Promise<void> {
    if (!jwt.enabled) {
        res.status(503).json({ error: 'Sandbox email test auth is not configured' })
        return
    }
    const teamId = Number(req.params.team_id)
    const body = TestSendRequestSchema.safeParse(req.body)
    if (!isAuthorized(jwt, req.headers.authorization, teamId, body.success ? body.data.hog_flow_id : undefined)) {
        res.status(403).json({ error: 'Forbidden' })
        return
    }
    if (!body.success) {
        res.status(400).json({ error: 'Invalid sandbox email test request' })
        return
    }
    if (!service) {
        res.json({ status: 'skipped', reason: 'sending_disabled' } satisfies SandboxEmailStepResult)
        return
    }
    const { hog_flow_id, action_id, email, message_category_id, message_category_type, email_sending_paused } =
        body.data
    const invocationId = randomUUID()
    const outcome = await service.send({
        teamId,
        hogFlowId: hog_flow_id,
        invocationId,
        capClaimId: invocationId,
        actionId: action_id,
        flowVersion: 0,
        isTest: true,
        workflowEmailPaused: email_sending_paused ?? false,
        email,
        categoryId: message_category_id,
        categoryType: message_category_type,
        claimSesSlot: () => (sesBucket ? claimSesSlot(sesBucket) : Promise.resolve(true)),
    })
    if (outcome.status !== 'retry') {
        void events.capture(teamId, outcome.status, {
            workflow_id: hog_flow_id,
            action_id,
            is_test: true,
            ...('reason' in outcome ? { reason: outcome.reason } : {}),
        })
    }
    res.json(toTestResult(outcome))
}

function isAuthorized(
    jwt: Pick<ScopedServiceJwt, 'verify'>,
    header: string | undefined,
    teamId: number,
    hogFlowId: string | undefined
): boolean {
    const token = header?.startsWith('Bearer ') ? header.slice('Bearer '.length) : undefined
    if (!token || !Number.isSafeInteger(teamId)) {
        return false
    }
    try {
        const claims = jwt.verify(token)
        return claims.team_id === teamId && (hogFlowId === undefined || claims.hog_flow_id === hogFlowId)
    } catch {
        return false
    }
}

function toTestResult(outcome: SandboxSendOutcome): SandboxEmailStepResult {
    switch (outcome.status) {
        case 'accepted':
            return { status: 'accepted', message_id: outcome.messageId }
        case 'retry':
            return outcome.reason === SEND_RATE_LIMITED
                ? { status: 'failed', reason: outcome.reason }
                : { status: 'pending', reason: outcome.reason }
        default:
            return { status: outcome.status, reason: outcome.reason }
    }
}
