import { z } from 'zod'

import {
    PendingApprovalSchema,
    waitIdentity,
    type ApprovalFlow,
    type ApprovalWait,
    type PollOutcome,
} from '@/core/approval'
import { HogError } from '@/core/errors'
import { ApiError, type PostHogApi } from '@/posthog/api'
import { HostSchema, type Host } from '@/posthog/host'
import { ProjectIdSchema, type ProjectId } from '@/posthog/ids'

import type { ProviderSettings } from './provider-settings'
import type { WorkloadConditions } from './providers/registry'

export const CI_SETUP_COMMAND = 'hog ci setup'
const POLL_INTERVAL_SECONDS = 5
// A request stays open for a day, so one wait stops well before that.
const MAX_WAIT_MS = 10 * 60_000

const ResolvedSubject = z.object({ subject: z.string(), subject_name: z.string() })

export type ResolvedSubject = z.output<typeof ResolvedSubject>

const RequestStatus = z.enum(['pending', 'approved', 'rejected', 'expired'])

const PolicyRequest = z.object({
    id: z.string(),
    status: RequestStatus,
    approval_url: z.string(),
    can_approve: z.boolean(),
    approvers: z.array(z.string()),
    expires_at: z.string(),
    policy_id: z.string().nullish(),
})

export const PendingPolicyRequestSchema = PendingApprovalSchema.extend({
    host: HostSchema,
    projectId: ProjectIdSchema,
    requestId: z.string(),
    provider: z.string(),
    subject: z.string(),
    conditions: z.record(z.string(), z.string()),
    scopes: z.array(z.string()),
    canApprove: z.boolean(),
    approvers: z.array(z.string()),
})

export interface ApprovedPolicy {
    policyId: string
    provider: string
    host: Host
    projectId: ProjectId
}

export type PendingPolicyRequest = z.output<typeof PendingPolicyRequestSchema>

export interface PolicyRequestInput {
    settings: ProviderSettings
    name: string
    subject: ResolvedSubject
    conditions: WorkloadConditions
    scopes: string[]
}

function requestsPath(projectId: ProjectId): string {
    return `/api/projects/${projectId}/workload_trust_policy_requests/`
}

export async function resolveSubject(
    api: PostHogApi,
    projectId: ProjectId,
    settings: ProviderSettings,
    subjectName: string,
    conditions: WorkloadConditions
): Promise<ResolvedSubject> {
    const query = new URLSearchParams({ issuer: settings.issuer, subject_name: subjectName })
    // PostHog refuses a lookup the policy's conditions rule out, like a repository on another forge.
    for (const [claim, value] of Object.entries(conditions)) {
        query.append('condition', `${claim}=${value}`)
    }
    try {
        return await api.get(`${requestsPath(projectId)}resolve_subject/?${query}`, ResolvedSubject)
    } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 503)) {
            throw error.withHint(`Pass the ID with --subject-id. ${settings.docs_url} says where to find it.`)
        }
        throw error
    }
}

function canonicalConditions(conditions: WorkloadConditions): string {
    return JSON.stringify(Object.entries(conditions).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
}

export function policyRequestFlow(
    api: PostHogApi,
    target: { host: Host; projectId: ProjectId },
    input: PolicyRequestInput
): ApprovalFlow<PendingPolicyRequest, ApprovedPolicy> {
    const { settings, subject, conditions, scopes } = input
    const same = (existing: PendingPolicyRequest): boolean =>
        existing.host === target.host &&
        existing.projectId === target.projectId &&
        existing.provider === settings.key &&
        existing.subject === subject.subject &&
        canonicalConditions(existing.conditions) === canonicalConditions(conditions) &&
        existing.scopes.join(' ') === scopes.join(' ')
    return {
        ...policyRequestWait(api, target),
        start: async () => {
            const created = await api.post(
                requestsPath(target.projectId),
                {
                    name: input.name,
                    issuer: settings.issuer,
                    subject: subject.subject,
                    subject_name: subject.subject_name,
                    conditions,
                    scopes,
                },
                PolicyRequest
            )
            return {
                url: created.approval_url,
                expiresAt: Date.parse(created.expires_at),
                intervalSeconds: POLL_INTERVAL_SECONDS,
                host: target.host,
                projectId: target.projectId,
                requestId: created.id,
                provider: settings.key,
                subject: subject.subject,
                conditions,
                scopes,
                canApprove: created.can_approve,
                approvers: created.approvers,
            }
        },
        reuse: same,
        refresh: async (existing) => {
            const current = await readRequest(api, existing)
            switch (current.status) {
                case 'pending':
                    return { ...existing, canApprove: current.can_approve, approvers: current.approvers }
                case 'approved':
                    // Nobody has to approve it again, and the first poll returns the policy.
                    return { ...existing, canApprove: true }
                default:
                    return undefined
            }
        },
        approver: (pending) =>
            pending.canApprove ? undefined : { who: 'an organization admin', names: pending.approvers },
    }
}

function readRequest(
    api: PostHogApi,
    pending: PendingPolicyRequest,
    timeoutMs?: number
): Promise<z.output<typeof PolicyRequest>> {
    return api.get(`${requestsPath(pending.projectId)}${pending.requestId}/`, PolicyRequest, { timeoutMs })
}

export function policyRequestWait(
    api: PostHogApi,
    target: { host: Host; projectId: ProjectId }
): ApprovalWait<PendingPolicyRequest, ApprovedPolicy> {
    return {
        ...waitIdentity(CI_SETUP_COMMAND),
        noun: 'policy request',
        pending: PendingPolicyRequestSchema,
        maxWaitMs: MAX_WAIT_MS,
        checkResumable: (pending) => {
            if (pending.host !== target.host || pending.projectId !== target.projectId) {
                throw new HogError(
                    'login_changed',
                    `The policy request is for project ${pending.projectId} on ${pending.host}, and you're logged in to project ${target.projectId} on ${target.host}.`,
                    `Run \`hog auth login --host ${pending.host}\` and pick project ${pending.projectId}, then run \`${CI_SETUP_COMMAND} --wait\` again.`
                )
            }
        },
        poll: async (pending, timeoutMs): Promise<PollOutcome<ApprovedPolicy>> => {
            const current = await readRequest(api, pending, timeoutMs)
            switch (current.status) {
                case 'pending':
                    return { state: 'pending' }
                case 'approved':
                    if (!current.policy_id) {
                        throw new HogError('unexpected_response', 'PostHog approved the request without a policy.')
                    }
                    return {
                        state: 'approved',
                        value: {
                            policyId: current.policy_id,
                            provider: pending.provider,
                            host: pending.host,
                            projectId: pending.projectId,
                        },
                    }
                case 'rejected':
                    return { state: 'rejected' }
                case 'expired':
                    return { state: 'expired' }
            }
        },
    }
}
