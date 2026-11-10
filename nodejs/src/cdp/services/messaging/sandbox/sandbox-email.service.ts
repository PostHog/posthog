import { createHash } from 'crypto'
import { Counter, Histogram } from 'prom-client'

import { PostgresRouter } from '~/common/utils/db/postgres'

import { MessageOptOutRecord } from '../../../types'
import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'
import { FrequencyCapCheck } from '../recipient-preferences.service'
import {
    AUTHORIZATION_TIMEOUT_MS,
    SandboxAuthorization,
    queryPrimaryBeforeDeadline,
    readSandboxAuthorization,
} from './sandbox-authorization'
import { SandboxCapClaim, SandboxCaps, claimSandboxCaps } from './sandbox-caps'
import { SandboxRenderedEmailSchema, buildSandboxMessage } from './sandbox-message'
import {
    SandboxRecipientCheck,
    SandboxRecipientCheckDependencies,
    SandboxRecipientCheckRequest,
    checkSandboxRecipient,
} from './sandbox-recipient-checks'
import { SES_TAG_ID, SandboxSesClient } from './sandbox-ses-client'
import { admitTenant } from './sandbox-tenant-admission'

export const SANDBOX_INTEGRATION_ID = 'posthog-managed-sandbox'

export type SandboxSendOutcome =
    | { status: 'accepted'; messageId: string }
    | { status: 'skipped' | 'failed'; reason: string }
    | { status: 'retry'; reason: string; capsClaimedFor?: string }

export type SandboxSendRequest = {
    teamId: number
    hogFlowId: string
    invocationId: string
    actionId: string
    flowVersion: number
    isTest: boolean
    parentRunId?: string
    email: unknown
    categoryId?: string
    categoryType?: 'marketing' | 'transactional'
    optOuts?: MessageOptOutRecord[]
    frequencyCap?: () => Promise<FrequencyCapCheck>
    capsClaimedFor?: string
}

export type SandboxEmailServiceDeps = {
    enabled: boolean
    fromAddress: string
    tenantName: string
    isProvisioned: (teamId: number) => Promise<boolean>
    authorize: (request: { teamId: number; recipient: string; tenantName: string }) => Promise<SandboxAuthorization>
    checkRecipient: (request: SandboxRecipientCheckRequest) => Promise<SandboxRecipientCheck>
    claimCaps: (claim: { organizationId: string; teamId: number; storedAddress: string }) => Promise<SandboxCapClaim>
    ses: Pick<SandboxSesClient, 'send'>
    now?: () => Date
}

const RETRYABLE_REFUSALS = new Set(['authorization_unavailable', 'pause_state_unavailable', 'cap_storage_unavailable'])
const MAX_ADDRESS_LENGTH = 254
const SINGLE_ADDRESS = /^[^\s@"<>,;:()[\]\\]+@[^\s@"<>,;:()[\]\\]+\.[^\s@"<>,;:()[\]\\]+$/
const LINE_BREAK = /[\r\n]/

const sandboxSendTotal = new Counter({
    name: 'cdp_sandbox_email_send_total',
    help: 'Sandbox email send attempts by outcome and reason',
    labelNames: ['outcome', 'reason'],
})

const sandboxSendDuration = new Histogram({
    name: 'cdp_sandbox_email_send_duration_seconds',
    help: 'Time from the start of a sandbox email send to its outcome',
    buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
})

export class SandboxEmailService {
    constructor(private readonly deps: SandboxEmailServiceDeps) {}

    async send(request: SandboxSendRequest): Promise<SandboxSendOutcome> {
        const stopTimer = sandboxSendDuration.startTimer()
        const outcome = await this.decide(request)
        stopTimer()
        sandboxSendTotal.inc({ outcome: outcome.status, reason: 'reason' in outcome ? outcome.reason : '' })
        return outcome
    }

    private async decide(request: SandboxSendRequest): Promise<SandboxSendOutcome> {
        if (!this.deps.enabled) {
            return { status: 'skipped', reason: 'sending_disabled' }
        }
        const email = SandboxRenderedEmailSchema.safeParse(request.email)
        if (!email.success) {
            return { status: 'failed', reason: 'render_failed' }
        }
        if (!SES_TAG_ID.test(request.actionId)) {
            return { status: 'failed', reason: 'unsupported_action_id' }
        }
        const provisioned = await this.deps.isProvisioned(request.teamId).catch(() => null)
        if (provisioned === null) {
            return refusal('authorization_unavailable', request.capsClaimedFor)
        }
        if (!provisioned) {
            return { status: 'skipped', reason: 'sandbox_not_provisioned' }
        }
        const address = parseSingleAddress(email.data.to.email)
        if (!address) {
            return { status: 'skipped', reason: 'invalid_recipient' }
        }
        const authorization = await this.deps.authorize({
            teamId: request.teamId,
            recipient: address,
            tenantName: this.deps.tenantName,
        })
        if (!authorization.ok) {
            return refusal(authorization.reason, request.capsClaimedFor)
        }
        const recipientCheck = await this.checkRecipient(request, [
            email.data.to.email,
            address,
            authorization.storedAddress,
        ])
        if (!recipientCheck.ok) {
            return refusal(recipientCheck.reason, request.capsClaimedFor)
        }
        const tenant = admitTenant(authorization.tenant, this.deps.now?.() ?? new Date())
        if (!tenant.ok) {
            return refusal(tenant.reason, request.capsClaimedFor)
        }
        const capsClaimedFor = capClaimHolder(authorization.organizationId, authorization.storedAddress)
        if (request.capsClaimedFor !== capsClaimedFor) {
            const caps = await this.deps.claimCaps({
                organizationId: authorization.organizationId,
                teamId: request.teamId,
                storedAddress: authorization.storedAddress,
            })
            if (!caps.ok) {
                return refusal(caps.reason, request.capsClaimedFor)
            }
        }
        const message = buildSandboxMessage({
            email: email.data,
            organizationId: authorization.organizationId,
            organizationName: authorization.organizationName,
            fromAddress: this.deps.fromAddress,
            recipient: authorization.storedAddress,
        })
        const { teamId, hogFlowId, invocationId, actionId, flowVersion, isTest, parentRunId } = request
        const sent = await this.deps.ses.send(message, {
            teamId,
            hogFlowId,
            invocationId,
            actionId,
            flowVersion,
            isTest,
            ...(parentRunId ? { parentRunId } : {}),
        })
        return sent.status === 'retry' && sent.reason === 'ses_throttled' ? { ...sent, capsClaimedFor } : sent
    }

    private async checkRecipient(request: SandboxSendRequest, spellings: string[]): Promise<SandboxRecipientCheck> {
        const addresses = [...new Set(spellings)]
        for (const [index, address] of addresses.entries()) {
            const last = index === addresses.length - 1
            const check = await this.deps.checkRecipient({
                ...this.recipientCheckBase(request),
                address,
                frequencyCap: last ? (request.frequencyCap ?? NO_FREQUENCY_CAP) : NO_FREQUENCY_CAP,
            })
            if (!check.ok || last) {
                return check
            }
        }
        return { ok: true }
    }

    private recipientCheckBase(
        request: SandboxSendRequest
    ): Omit<SandboxRecipientCheckRequest, 'address' | 'frequencyCap'> {
        return {
            teamId: request.teamId,
            categoryId: request.categoryId,
            categoryType: request.categoryType,
            optOuts: request.optOuts ?? [],
            isTest: request.isTest,
        }
    }
}

const NO_FREQUENCY_CAP = (): Promise<FrequencyCapCheck> => Promise.resolve({ capped: false })

function capClaimHolder(organizationId: string, storedAddress: string): string {
    return createHash('sha256').update(`${organizationId}/${storedAddress.toLowerCase()}`).digest('hex')
}

function refusal(reason: string, capsClaimedFor: string | undefined): SandboxSendOutcome {
    if (!RETRYABLE_REFUSALS.has(reason)) {
        return { status: 'skipped', reason }
    }
    return capsClaimedFor ? { status: 'retry', reason, capsClaimedFor } : { status: 'retry', reason }
}

function parseSingleAddress(raw: string): string | null {
    if (LINE_BREAK.test(raw)) {
        return null
    }
    const address = raw.trim()
    return address.length <= MAX_ADDRESS_LENGTH && SINGLE_ADDRESS.test(address) ? address : null
}

export function createSandboxEmailService({
    enabled,
    db,
    recipientChecks,
    limiter,
    caps,
    ses,
    fromAddress,
    tenantName,
}: {
    enabled: boolean
    db: PostgresRouter
    recipientChecks: SandboxRecipientCheckDependencies
    limiter: RateLimiterService
    caps: SandboxCaps
    ses: Pick<SandboxSesClient, 'send'>
    fromAddress: string
    tenantName: string
}): SandboxEmailService {
    return new SandboxEmailService({
        enabled,
        fromAddress,
        tenantName,
        isProvisioned: (teamId) => hasSandboxSenderRow(db, teamId),
        authorize: (request) => readSandboxAuthorization(db, request),
        checkRecipient: (request) => checkSandboxRecipient(recipientChecks, request),
        claimCaps: (claim) => claimSandboxCaps(limiter, caps, claim),
        ses,
    })
}

export async function hasSandboxSenderRow(db: PostgresRouter, teamId: number): Promise<boolean> {
    const rows = await queryPrimaryBeforeDeadline(
        db,
        `SELECT 1 FROM posthog_integration WHERE team_id = $1 AND kind = 'email_sandbox' AND integration_id = $2`,
        [teamId, SANDBOX_INTEGRATION_ID],
        AUTHORIZATION_TIMEOUT_MS,
        'sandbox-email-provisioned'
    )
    return rows.length > 0
}
