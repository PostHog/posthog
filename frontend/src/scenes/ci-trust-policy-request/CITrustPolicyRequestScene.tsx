import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { fullNameOrEmail } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CITrustPolicyRequestLogicProps, ciTrustPolicyRequestLogic } from './ciTrustPolicyRequestLogic'

export const scene: SceneExport<CITrustPolicyRequestLogicProps> = {
    component: CITrustPolicyRequestScene,
    logic: ciTrustPolicyRequestLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

const STATUS_TAG: Record<string, { label: string; type: 'warning' | 'success' | 'danger' | 'muted' }> = {
    pending: { label: 'Pending', type: 'warning' },
    approved: { label: 'Approved', type: 'success' },
    rejected: { label: 'Rejected', type: 'danger' },
    expired: { label: 'Expired', type: 'muted' },
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-x-4 gap-y-1 py-2 border-b last:border-b-0">
            <div className="w-40 shrink-0 text-secondary">{label}</div>
            <div className="flex-1 min-w-0 break-words">{children}</div>
        </div>
    )
}

export function CITrustPolicyRequestScene({ id }: CITrustPolicyRequestLogicProps): JSX.Element {
    const { policyRequest, policyRequestLoading, policyRequestMissing, resolving } = useValues(
        ciTrustPolicyRequestLogic({ id })
    )
    const { approve, reject } = useActions(ciTrustPolicyRequestLogic({ id }))

    if (policyRequestMissing) {
        return (
            <SceneContent>
                <LemonBanner type="error">
                    Couldn't load this request. It may not exist, or you may not have access to this project.
                </LemonBanner>
            </SceneContent>
        )
    }

    if (!policyRequest) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-40" active={policyRequestLoading} />
            </SceneContent>
        )
    }

    const status = STATUS_TAG[policyRequest.status] ?? STATUS_TAG.pending
    const requester = policyRequest.requested_by
    const isPending = policyRequest.status === 'pending'

    return (
        <SceneContent>
            <SceneTitleSection
                name={`CI trust policy request: ${policyRequest.name}`}
                resourceType={{ type: 'settings' }}
            />
            <div className="max-w-200 deprecated-space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonTag type={status.type}>{status.label}</LemonTag>
                    <span className="text-secondary">
                        Requested by <strong>{requester ? fullNameOrEmail(requester) : 'a former member'}</strong>
                        {requester ? ` (${requester.email})` : ''} through {policyRequest.requested_via || 'the API'}
                    </span>
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
                </div>

                <p>
                    Approving creates a CI trust policy for this project. CI jobs that match it get short-lived tokens
                    that act as the organization owner, with only the scopes below.
                </p>

                <div className="border rounded px-4">
                    <DetailRow label="Policy name">{policyRequest.name}</DetailRow>
                    <DetailRow label="CI provider">{policyRequest.provider_name ?? policyRequest.issuer}</DetailRow>
                    <DetailRow label="Issuer">
                        <span className="font-mono">{policyRequest.issuer}</span>
                    </DetailRow>
                    <DetailRow label="Repository">
                        <span className="font-mono">{policyRequest.repository}</span>{' '}
                        <span className="text-secondary">(ID {policyRequest.repository_id})</span>
                    </DetailRow>
                    <DetailRow label="Ref">
                        {policyRequest.ref || <span className="text-secondary">Any ref</span>}
                    </DetailRow>
                    <DetailRow label="Environment">
                        {policyRequest.environment || <span className="text-secondary">Any environment</span>}
                    </DetailRow>
                    <DetailRow label="Scopes">
                        <span className="flex flex-wrap gap-1">
                            {policyRequest.scopes.map((scope) => (
                                <LemonTag key={scope}>{scope}</LemonTag>
                            ))}
                        </span>
                    </DetailRow>
                    <DetailRow label={isPending ? 'Expires' : 'Requested'}>
                        <TZLabel time={isPending ? policyRequest.expires_at : policyRequest.created_at} />
                    </DetailRow>
                </div>

                {policyRequest.status === 'approved' ? (
                    <LemonBanner type="success">
                        Approved
                        {policyRequest.resolved_by ? ` by ${fullNameOrEmail(policyRequest.resolved_by)}` : ''}. The
                        policy is active.{' '}
                        <Link to={urls.settings('environment-ci-trust-policies')}>See CI trust policies</Link>
                    </LemonBanner>
                ) : null}

                {isPending && policyRequest.can_approve ? (
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="primary"
                            onClick={() => approve()}
                            loading={resolving === 'approve'}
                            disabledReason={resolving ? 'Saving' : undefined}
                            data-attr="ci-trust-policy-request-approve"
                        >
                            Approve and create policy
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => reject()}
                            loading={resolving === 'reject'}
                            disabledReason={resolving ? 'Saving' : undefined}
                            data-attr="ci-trust-policy-request-reject"
                        >
                            Reject
                        </LemonButton>
                    </div>
                ) : null}

                {isPending && !policyRequest.can_approve ? (
                    <LemonBanner type="info">
                        Only organization admins and owners can approve this request
                        {policyRequest.approvers.length > 0 ? `: ${policyRequest.approvers.join(', ')}` : ''}. Send them
                        this page's link.
                    </LemonBanner>
                ) : null}
            </div>
        </SceneContent>
    )
}
