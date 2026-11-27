import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'

import type { ServiceAccountAPIKeyApi } from '~/generated/core/api.schemas'

import { QuillServiceAccountDetails } from './QuillServiceAccountDetails'
import { ServiceAccountLogicProps, serviceAccountLogic } from './serviceAccountLogic'
import { serviceAccountsLogic } from './serviceAccountsLogic'

export function ServiceAccountDetails(props: ServiceAccountLogicProps): JSX.Element {
    const logic = serviceAccountLogic(props)
    const { account, accountLoading, accountLoadFailed, apiKeys, apiKeysLoading, keysLoadFailed } = useValues(logic)
    const { loadAccount, loadApiKeys } = useActions(logic)
    const { selectAccount } = useActions(serviceAccountsLogic({ organizationId: props.organizationId }))
    const { currentOrganization } = useValues(organizationLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillServiceAccountDetails {...props} />
    }

    return (
        <div className="space-y-4">
            <LemonButton
                type="tertiary"
                icon={<IconArrowLeft />}
                onClick={() => selectAccount(null)}
                data-attr="service-account-back"
            >
                All service accounts
            </LemonButton>
            {accountLoadFailed && !accountLoading ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadAccount }}>
                    Couldn't load this service account. It may no longer be available. Try again or return to the list.
                </LemonBanner>
            ) : account === null ? (
                <LemonSkeleton className="h-16" />
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-2">
                        <h3 className="mb-0 break-words">{account.name}</h3>
                        <LemonTag type={account.is_active ? 'success' : 'default'}>
                            {account.is_active ? 'Active' : 'Disabled'}
                        </LemonTag>
                    </div>
                    <div className="text-muted">
                        Created <TZLabel time={account.created_at} />
                    </div>
                    <h4>API keys</h4>
                    <p>
                        Keys authenticate as this service account. Each key can limit its API scopes and project access.
                        Only masked values are shown.
                    </p>
                    {keysLoadFailed && !apiKeysLoading ? (
                        <LemonBanner type="error" action={{ children: 'Retry', onClick: loadApiKeys }}>
                            Couldn't load API keys. Try again.
                        </LemonBanner>
                    ) : apiKeys === null ? (
                        <LemonSkeleton className="h-32" />
                    ) : (
                        <LemonTable<ServiceAccountAPIKeyApi>
                            dataSource={apiKeys}
                            loading={apiKeysLoading}
                            rowKey="id"
                            pagination={{ pageSize: 20 }}
                            emptyState="This service account has no API keys."
                            columns={[
                                {
                                    title: 'Key',
                                    key: 'label',
                                    render: (_, key) => (
                                        <div className="flex flex-col gap-1">
                                            <strong className="break-words">{key.label}</strong>
                                            <code>{key.mask_value}</code>
                                            <span className="text-muted text-xs">
                                                Created <TZLabel time={key.created_at} />
                                            </span>
                                            <span className="text-muted text-xs">
                                                {key.expires_at ? (
                                                    <>
                                                        Expires <TZLabel time={key.expires_at} />
                                                    </>
                                                ) : (
                                                    'Never expires'
                                                )}
                                            </span>
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Access',
                                    key: 'scopes',
                                    render: (_, key) => (
                                        <div className="flex flex-col gap-2">
                                            <div className="flex flex-wrap gap-1">
                                                {key.scopes.map((scope) => (
                                                    <LemonTag key={scope}>{scope}</LemonTag>
                                                ))}
                                            </div>
                                            <span className="text-muted text-xs">
                                                {key.scoped_organizations?.length &&
                                                !key.scoped_organizations.includes(props.organizationId)
                                                    ? 'No access to this organization'
                                                    : key.scoped_teams?.length
                                                      ? key.scoped_teams
                                                            .map(
                                                                (id) =>
                                                                    currentOrganization?.teams.find(
                                                                        (team) => team.id === id
                                                                    )?.name ?? `Project ${id}`
                                                            )
                                                            .join(', ')
                                                      : 'All projects the account can access'}
                                            </span>
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Last used',
                                    key: 'last_used_at',
                                    render: (_, key) =>
                                        key.last_used_at ? <TZLabel time={key.last_used_at} /> : 'Never',
                                },
                            ]}
                        />
                    )}
                </>
            )}
        </div>
    )
}
