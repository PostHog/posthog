import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { ServiceAccountApi } from '~/generated/core/api.schemas'

import { CreateServiceAccountModal } from './CreateServiceAccountModal'
import { QuillServiceAccountsTable } from './QuillServiceAccountsTable'
import { ServiceAccountDetails } from './ServiceAccountDetails'
import { ServiceAccountsLogicProps, serviceAccountsLogic } from './serviceAccountsLogic'

export function ServiceAccountsTable(props: ServiceAccountsLogicProps): JSX.Element {
    const logic = serviceAccountsLogic(props)
    const { accounts, filteredAccounts, accountsLoading, loadFailed, search, selectedAccountId } = useValues(logic)
    const { loadAccounts, setSearch, setCreating, selectAccount } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (selectedAccountId) {
        return <ServiceAccountDetails organizationId={props.organizationId} accountId={selectedAccountId} />
    }
    if (todayRailNav) {
        return <QuillServiceAccountsTable {...props} />
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search service accounts"
                    aria-label="Search service accounts"
                    value={search}
                    onChange={setSearch}
                    className="max-w-80"
                />
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => setCreating(true)}
                    data-attr="service-account-create"
                    className="ml-auto"
                >
                    Create service account
                </LemonButton>
            </div>
            {loadFailed && !accountsLoading ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadAccounts() }}>
                    Couldn't load service accounts. Try again.
                </LemonBanner>
            ) : accounts === null ? (
                <LemonSkeleton className="h-32" />
            ) : (
                <LemonTable<ServiceAccountApi>
                    dataSource={filteredAccounts}
                    loading={accountsLoading}
                    rowKey="id"
                    pagination={{ pageSize: 20 }}
                    emptyState={
                        search.trim()
                            ? 'No service accounts match your search.'
                            : 'No service accounts yet. Create one for an integration or automation.'
                    }
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, account) => (
                                <LemonButton
                                    type="tertiary"
                                    onClick={() => selectAccount(account.id)}
                                    data-attr="service-account-open"
                                >
                                    <span className="truncate max-w-60">{account.name}</span>
                                </LemonButton>
                            ),
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, account) => (
                                <LemonTag type={account.is_active ? 'success' : 'default'}>
                                    {account.is_active ? 'Active' : 'Disabled'}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Created',
                            key: 'created_at',
                            render: (_, account) => <TZLabel time={account.created_at} />,
                        },
                    ]}
                />
            )}
            <CreateServiceAccountModal {...props} />
        </div>
    )
}
