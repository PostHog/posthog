import { z } from 'zod'

import { PendingApprovalSchema, type ApprovalFlow, type ApprovalWait, type PollOutcome } from '@/core/approval'
import { HogError } from '@/core/errors'
import { ApiError, type PostHogApi } from '@/posthog/api'
import { HostSchema, type Host } from '@/posthog/host'
import { ProjectIdSchema, type ProjectId } from '@/posthog/ids'

import type { WorkloadConditions, WorkloadProvider } from './providers'

export const CI_SETUP_COMMAND = 'hog ci setup'
const POLL_INTERVAL_SECONDS = 5
// A request stays open for a day, so one wait stops well before that.
const MAX_WAIT_MS = 10 * 60_000

const ResolvedSubject = z.object({ subject: z.string(), subject_name: z.string(), found_via: z.string() })

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
    provider: WorkloadProvider
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
    provider: WorkloadProvider,
    subjectName: string
): Promise<ResolvedSubject> {
    const query = new URLSearchParams({ issuer: provider.issuer, subject_name: subjectName })
    try {
        return await api.get(`${requestsPath(projectId)}resolve_subject/?${query}`, ResolvedSubject)
    } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 503)) {
            throw error.withHint(`Pass the ID with --subject-id. ${provider.docsUrl} says where to find it.`)
        }
        throw error
    }
}

export function policyRequestFlow(
    api: PostHogApi,
    target: { host: Host; projectId: ProjectId },
    input: PolicyRequestInput
): ApprovalFlow<PendingPolicyRequest, ApprovedPolicy> {
    const { provider, subject, conditions, scopes } = input
    const same = (existing: PendingPolicyRequest): boolean =>
        existing.host === target.host &&
        existing.projectId === target.projectId &&
        existing.provider === provider.key &&
        existing.subject === subject.subject &&
        JSON.stringify(existing.conditions) === JSON.stringify(conditions) &&
        existing.scopes.join(' ') === scopes.join(' ')
    return {
        ...policyRequestWait(api, target),
        start: async () => {
            const created = await api.post(
                requestsPath(target.projectId),
                {
                    name: input.name,
                    issuer: provider.issuer,
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
                provider: provider.key,
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
            return current.status === 'pending'
                ? { ...existing, canApprove: current.can_approve, approvers: current.approvers }
                : undefined
        },
        approver: (pending) =>
            pending.canApprove
                ? undefined
                : `an organization admin${pending.approvers.length > 0 ? ` (${pending.approvers.join(', ')})` : ''}`,
    }
}

function readRequest(api: PostHogApi, pending: PendingPolicyRequest): Promise<z.output<typeof PolicyRequest>> {
    return api.get(`${requestsPath(pending.projectId)}${pending.requestId}/`, PolicyRequest)
}

export function policyRequestWait(
    api: PostHogApi,
    target: { host: Host; projectId: ProjectId }
): ApprovalWait<PendingPolicyRequest, ApprovedPolicy> {
    return {
        command: CI_SETUP_COMMAND,
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
        poll: async (pending): Promise<PollOutcome<ApprovedPolicy>> => {
            const current = await readRequest(api, pending)
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
