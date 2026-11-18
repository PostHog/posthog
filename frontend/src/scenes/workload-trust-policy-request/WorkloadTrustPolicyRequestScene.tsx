import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { fullNameOrEmail } from 'lib/utils/strings'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES, type AuthNotes } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { WorkloadTrustPolicyRequestApi } from '~/generated/core/api.schemas'

import {
    WorkloadTrustPolicyRequestLogicProps,
    workloadTrustPolicyRequestLogic,
} from './workloadTrustPolicyRequestLogic'

export const scene: SceneExport<WorkloadTrustPolicyRequestLogicProps> = {
    component: WorkloadTrustPolicyRequestScene,
    logic: workloadTrustPolicyRequestLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-x-4 gap-y-1 py-2 border-b last:border-b-0">
            <div className="w-28 shrink-0 text-secondary text-sm">{label}</div>
            <div className="flex-1 min-w-0 break-words text-sm">{children}</div>
        </div>
    )
}

function RequesterLine({ policyRequest }: { policyRequest: WorkloadTrustPolicyRequestApi }): JSX.Element {
    const requester = policyRequest.requested_by
    return (
        <>
            Requested by <strong>{requester ? fullNameOrEmail(requester) : 'a former member'}</strong>
            {requester ? ` (${requester.email})` : ''}
            {policyRequest.requested_via ? ` through ${policyRequest.requested_via}` : ''}{' '}
            {policyRequest.requested_via_verified === true ? (
                <Tooltip title="This application has been verified by PostHog.">
                    <LemonTag type="success" size="small">
                        Verified
                    </LemonTag>
                </Tooltip>
            ) : policyRequest.requested_via_verified === false ? (
                <Tooltip title="This application has not been verified by PostHog. Only approve if you recognize the requester and the application.">
                    <LemonTag type="warning" size="small">
                        Unverified application
                    </LemonTag>
                </Tooltip>
            ) : null}
        </>
    )
}

function notesFor(policyRequest: WorkloadTrustPolicyRequestApi | null, missing: boolean): AuthNotes {
    if (missing) {
        return AUTH_NOTES.workloadTrustPolicyRequest.missing
    }
    if (policyRequest?.status === 'approved') {
        return AUTH_NOTES.workloadTrustPolicyRequest.approved
    }
    if (policyRequest && policyRequest.status !== 'pending') {
        return AUTH_NOTES.workloadTrustPolicyRequest.closed
    }
    return AUTH_NOTES.workloadTrustPolicyRequest.pending
}

export function WorkloadTrustPolicyRequestScene({ id }: WorkloadTrustPolicyRequestLogicProps): JSX.Element {
    const { policyRequest, policyRequestLoading, policyRequestMissing, resolving } = useValues(
        workloadTrustPolicyRequestLogic({ id })
    )
    const { approve, reject } = useActions(workloadTrustPolicyRequestLogic({ id }))

    return (
        <AuthScene notes={notesFor(policyRequest, policyRequestMissing)}>
            <AuthSceneCard>
                {policyRequestMissing ? (
                    <>
                        <AuthCardTitle title="Request not found" />
                        <AuthBanner variant="danger">
                            Couldn't load this request. It may not exist, or you may not have access to this project.
                        </AuthBanner>
                    </>
                ) : !policyRequest ? (
                    <LemonSkeleton className="h-60" active={policyRequestLoading} />
                ) : (
                    <RequestDetails
                        policyRequest={policyRequest}
                        resolving={resolving}
                        onApprove={approve}
                        onReject={reject}
                    />
                )}
            </AuthSceneCard>
        </AuthScene>
    )
}

function RequestDetailTable({
    policyRequest,
    isPending,
}: {
    policyRequest: WorkloadTrustPolicyRequestApi
    isPending: boolean
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const claimLabels = policyRequest.claim_labels
    const conditions = policyRequest.conditions ?? {}
    // A claim the provider no longer offers still shows, so the admin sees every condition they approve.
    const conditionClaims = [...new Set([...Object.keys(claimLabels.conditions), ...Object.keys(conditions)])]

    return (
        <div className="border rounded px-3">
            {/* An approval link can switch the app into another organization, so name where the access goes. */}
            <DetailRow label="Project">
                {currentTeam?.name} <span className="text-secondary">in {currentOrganization?.name}</span>
            </DetailRow>
            <DetailRow label="Name">{policyRequest.name}</DetailRow>
            <DetailRow label="Provider">{policyRequest.provider_name ?? policyRequest.issuer}</DetailRow>
            <DetailRow label={claimLabels.subject_name}>
                <span className="font-mono">{policyRequest.subject_name}</span>
            </DetailRow>
            <DetailRow label={claimLabels.subject}>
                <span className="font-mono">{policyRequest.subject}</span>
            </DetailRow>
            {conditionClaims.map((claim) => (
                <DetailRow key={claim} label={claimLabels.conditions[claim] ?? claim}>
                    {conditions[claim] || <span className="text-secondary">Any value</span>}
                </DetailRow>
            ))}
            <DetailRow label="Scopes">
                <span className="flex flex-wrap gap-1">
                    {policyRequest.scopes.map((scope) => (
                        <LemonTag key={scope} type={scope in policyRequest.risky_scopes ? 'warning' : 'default'}>
                            {scope}
                        </LemonTag>
                    ))}
                </span>
            </DetailRow>
            <DetailRow label={isPending ? 'Expires' : 'Requested'}>
                <TZLabel time={isPending ? policyRequest.expires_at : policyRequest.created_at} />
            </DetailRow>
        </div>
    )
}

function RequestActions({
    policyRequest,
    resolving,
    onApprove,
    onReject,
}: {
    policyRequest: WorkloadTrustPolicyRequestApi
    resolving: 'approve' | 'reject' | null
    onApprove: () => void
    onReject: () => void
}): JSX.Element {
    if (!policyRequest.can_approve) {
        return (
            <AuthBanner variant="note">
                Only organization admins and owners can approve this request
                {policyRequest.approvers.length > 0 ? `: ${policyRequest.approvers.join(', ')}` : ''}. Send them this
                page's link.
            </AuthBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonButton
                type="primary"
                size="large"
                fullWidth
                center
                onClick={onApprove}
                loading={resolving === 'approve'}
                disabledReason={resolving ? 'Saving' : undefined}
                data-attr="workload-trust-policy-request-approve"
            >
                Approve
            </LemonButton>
            <LemonButton
                type="secondary"
                status="danger"
                fullWidth
                center
                onClick={onReject}
                loading={resolving === 'reject'}
                disabledReason={resolving ? 'Saving' : undefined}
                data-attr="workload-trust-policy-request-reject"
            >
                Reject
            </LemonButton>
        </div>
    )
}

function RequestDetails({
    policyRequest,
    resolving,
    onApprove,
    onReject,
}: {
    policyRequest: WorkloadTrustPolicyRequestApi
    resolving: 'approve' | 'reject' | null
    onApprove: () => void
    onReject: () => void
}): JSX.Element {
    const isPending = policyRequest.status === 'pending'
    const riskyScopes = Object.entries(policyRequest.risky_scopes)

    return (
        <div className="flex flex-col gap-4">
            <AuthCardTitle
                className="mb-0"
                title={isPending ? 'Trust this workload?' : `This request was ${policyRequest.status}`}
                sub={<RequesterLine policyRequest={policyRequest} />}
            />

            {isPending ? (
                <p className="m-0 text-sm">
                    Approving adds a trusted workload to this project. Workloads that match it get short-lived tokens
                    that act as the organization owner, with only the scopes below.
                </p>
            ) : null}

            <RequestDetailTable policyRequest={policyRequest} isPending={isPending} />

            {isPending && riskyScopes.length > 0 ? (
                <AuthBanner variant="warning">
                    <p className="m-0 font-semibold">Add these scopes with care</p>
                    <ul className="m-0 mt-1 pl-4 list-disc">
                        {riskyScopes.map(([scope, warning]) => (
                            <li key={scope}>
                                <code>{scope}</code>: {warning}
                            </li>
                        ))}
                    </ul>
                </AuthBanner>
            ) : null}

            {policyRequest.status === 'approved' ? (
                <AuthBanner variant="success">
                    Approved
                    {policyRequest.resolved_by ? ` by ${fullNameOrEmail(policyRequest.resolved_by)}` : ''}. The policy
                    is active. <Link to={urls.settings('environment-trusted-workloads')}>See trusted workloads</Link>
                </AuthBanner>
            ) : null}

            {isPending ? (
                <RequestActions
                    policyRequest={policyRequest}
                    resolving={resolving}
                    onApprove={onApprove}
                    onReject={onReject}
                />
            ) : null}
        </div>
    )
}
