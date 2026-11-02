import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { CITrustPolicyApi } from '~/generated/core/api.schemas'

import { ciTrustPoliciesLogic } from './ciTrustPoliciesLogic'
import { CITrustPolicyModal } from './CITrustPolicyModal'

export function CITrustPolicies(): JSX.Element {
    const { policies, policiesLoading, policiesLoadFailed, providers, providersLoadFailed, providerNames } =
        useValues(ciTrustPoliciesLogic)
    const { setEditingPolicyId, deletePolicy, setPolicyEnabled, loadPolicies, loadProviders } =
        useActions(ciTrustPoliciesLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const createDisabledReason =
        providers === null
            ? providersLoadFailed
                ? "Couldn't load the supported CI providers"
                : 'Loading the supported CI providers'
            : providers.supported.length === 0
              ? 'No CI provider is supported on this instance'
              : undefined

    return (
        <>
            <p>
                A CI trust policy lets CI jobs from one repository get short-lived tokens for this project, so you don't
                have to store an API key in your CI provider. Tokens act as the organization owner and carry only the
                scopes the policy lists.
            </p>
            {restrictionReason ? (
                <LemonBanner type="info" className="mb-4">
                    Only organization admins and owners can create or change CI trust policies.
                </LemonBanner>
            ) : (
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => setEditingPolicyId('new')}
                    disabledReason={createDisabledReason}
                    data-attr="ci-trust-policy-create"
                    className="mb-4"
                >
                    Create CI trust policy
                </LemonButton>
            )}
            {providersLoadFailed ? (
                <LemonBanner
                    type="error"
                    className="mb-4"
                    action={{ children: 'Retry', onClick: () => loadProviders() }}
                >
                    Couldn't load the supported CI providers.
                </LemonBanner>
            ) : null}
            {providers && providers.unsupported.length > 0 ? (
                <p className="text-secondary text-sm">
                    Not supported:{' '}
                    {providers.unsupported.map((provider, index) => (
                        <span key={provider.key}>
                            {index > 0 ? '; ' : ''}
                            <strong>{provider.name}</strong> ({provider.reason.replace(/\.$/, '')})
                        </span>
                    ))}
                    .
                </p>
            ) : null}
            {policiesLoadFailed ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadPolicies() }}>
                    Couldn't load CI trust policies.
                </LemonBanner>
            ) : (
                <LemonTable<CITrustPolicyApi>
                    dataSource={policies ?? []}
                    loading={policiesLoading && policies === null}
                    rowKey="id"
                    emptyState="No CI trust policies yet. CI jobs can't get tokens for this project."
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
                            title: 'Repository',
                            key: 'repository',
                            render: (_, policy) => (
                                <div className="flex flex-col">
                                    <span className="font-mono">{policy.repository}</span>
                                    <span className="text-secondary text-xs">ID {policy.repository_id}</span>
                                </div>
                            ),
                        },
                        {
                            title: 'Runs on',
                            key: 'conditions',
                            render: (_, policy) => (
                                <span className="flex flex-wrap gap-1">
                                    {policy.ref ? <LemonTag>ref: {policy.ref}</LemonTag> : null}
                                    {policy.environment ? <LemonTag>environment: {policy.environment}</LemonTag> : null}
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
                                    disabledReason={restrictionReason ?? (policiesLoading ? 'Saving' : undefined)}
                                    data-attr="ci-trust-policy-enabled"
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
                            render: (_, policy) =>
                                restrictionReason ? null : (
                                    <LemonMenu
                                        items={[
                                            { label: 'Edit', onClick: () => setEditingPolicyId(policy.id) },
                                            {
                                                label: 'Delete',
                                                status: 'danger',
                                                onClick: () => deletePolicy(policy),
                                                'data-attr': 'ci-trust-policy-delete',
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
            <CITrustPolicyModal />
        </>
    )
}
