import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TimeSensitiveAuthenticationArea } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { WorkloadProvidersResponseApi, WorkloadTrustPolicyApi } from '~/generated/core/api.schemas'

import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'
import { WorkloadTrustPolicyModal } from './WorkloadTrustPolicyModal'

function getCreateDisabledReason(
    providers: WorkloadProvidersResponseApi | null,
    providersLoadFailed: boolean,
    policiesLoading: boolean
): string | undefined {
    if (providers === null) {
        return providersLoadFailed ? "Couldn't load the supported providers" : 'Loading the supported providers'
    }
    if (providers.supported.length === 0) {
        return 'No workload provider is supported on this instance'
    }
    // A list response that lands after a save would replace the new policy with an older snapshot.
    return policiesLoading ? 'Loading trusted workloads' : undefined
}

export function WorkloadTrustPolicies(): JSX.Element {
    const { policies, policiesLoading, policiesLoadFailed, providers, providersLoadFailed, providerNames } =
        useValues(workloadTrustPoliciesLogic)
    const { setEditingPolicyId, deletePolicy, setPolicyEnabled, loadPolicies, loadProviders } =
        useActions(workloadTrustPoliciesLogic)

    const createDisabledReason = getCreateDisabledReason(providers, providersLoadFailed, policiesLoading)

    // Policies hand out tokens that act as the organization owner, so the section asks for a recent login.
    return (
        <TimeSensitiveAuthenticationArea>
            <>
                <p>
                    A trusted workload, such as a CI job, gets short-lived tokens for this project, so you don't have to
                    store an API key with it. Tokens act as the organization owner and carry only the scopes the policy
                    lists.
                </p>
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => setEditingPolicyId('new')}
                    disabledReason={createDisabledReason}
                    data-attr="workload-trust-policy-create"
                    className="mb-4"
                >
                    Add trusted workload
                </LemonButton>
                {providersLoadFailed ? (
                    <LemonBanner
                        type="error"
                        className="mb-4"
                        action={{ children: 'Retry', onClick: () => loadProviders() }}
                    >
                        Couldn't load the supported providers.
                    </LemonBanner>
                ) : null}
                {policiesLoadFailed ? (
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadPolicies() }}>
                        Couldn't load trusted workloads.
                    </LemonBanner>
                ) : (
                    <LemonTable<WorkloadTrustPolicyApi>
                        dataSource={policies ?? []}
                        loading={policiesLoading && policies === null}
                        rowKey="id"
                        emptyState="No trusted workloads yet. No workload can get tokens for this project."
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, policy) => (
                                    <div className="flex flex-col">
                                        <span className="font-semibold">{policy.name}</span>
                                        <span className="text-secondary text-xs">
                                            {providerNames[policy.issuer] ?? policy.issuer}
                                        </span>
                                    </div>
                                ),
                            },
                            {
                                title: 'Workload',
                                key: 'subject',
                                render: (_, policy) => (
                                    <div className="flex flex-col">
                                        <span className="font-mono">{policy.subject_name}</span>
                                        <span className="text-secondary text-xs">
                                            {policy.claim_labels.subject} {policy.subject}
                                        </span>
                                    </div>
                                ),
                            },
                            {
                                title: 'Conditions',
                                key: 'conditions',
                                render: (_, policy) => (
                                    <span className="flex flex-wrap gap-1">
                                        {Object.entries(policy.conditions ?? {}).map(([claim, value]) => (
                                            <LemonTag key={claim}>
                                                {policy.claim_labels.conditions[claim] ?? claim}: {value}
                                            </LemonTag>
                                        ))}
                                    </span>
                                ),
                            },
                            {
                                title: 'Scopes',
                                key: 'scopes',
                                render: (_, policy) => (
                                    <span className="flex flex-wrap gap-1">
                                        {policy.scopes.map((scope) => (
                                            <LemonTag key={scope}>{scope}</LemonTag>
                                        ))}
                                    </span>
                                ),
                            },
                            {
                                title: 'Enabled',
                                key: 'enabled',
                                render: (_, policy) => (
                                    <LemonSwitch
                                        checked={!!policy.enabled}
                                        onChange={(enabled) => setPolicyEnabled({ policy, enabled })}
                                        disabledReason={policiesLoading ? 'Saving' : undefined}
                                        data-attr="workload-trust-policy-enabled"
                                    />
                                ),
                            },
                            {
                                title: 'Created',
                                key: 'created',
                                render: (_, policy) => (
                                    <div className="flex flex-col gap-1">
                                        {policy.created_by ? (
                                            <ProfilePicture
                                                user={{
                                                    first_name: policy.created_by.first_name,
                                                    last_name: policy.created_by.last_name,
                                                    email: policy.created_by.email,
                                                }}
                                                size="sm"
                                                showName
                                            />
                                        ) : null}
                                        <TZLabel time={policy.created_at} className="text-secondary text-xs" />
                                    </div>
                                ),
                            },
                            {
                                key: 'actions',
                                width: 0,
                                render: (_, policy) => (
                                    <LemonMenu
                                        items={[
                                            { label: 'Edit', onClick: () => setEditingPolicyId(policy.id) },
                                            {
                                                label: 'Delete',
                                                status: 'danger',
                                                onClick: () => deletePolicy(policy),
                                                'data-attr': 'workload-trust-policy-delete',
                                            },
                                        ]}
                                    >
                                        <LemonButton size="small" icon={<IconEllipsis />} aria-label="Policy actions" />
                                    </LemonMenu>
                                ),
                            },
                        ]}
                    />
                )}
                <WorkloadTrustPolicyModal />
            </>
        </TimeSensitiveAuthenticationArea>
    )
}
