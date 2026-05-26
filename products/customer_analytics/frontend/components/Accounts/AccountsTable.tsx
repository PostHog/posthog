import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns, ProfilePicture } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_PAGE_SIZE, accountsLogic } from './accountsLogic'

type AccountAssignment = { id: number; email: string } | null

export function AccountsTable(): JSX.Element {
    const { results, totalCount, accountsLoading, currentPage } = useValues(accountsLogic)
    const { setCurrentPage } = useActions(accountsLogic)

    const columns: LemonTableColumns<AccountApi> = [
        {
            title: 'Account',
            key: 'name',
            dataIndex: 'name',
            render: (_, account) => (
                <div className="flex flex-col min-w-40">
                    <span className="font-medium">{account.name}</span>
                    {account.external_id ? (
                        <CopyToClipboardInline
                            explicitValue={account.external_id}
                            iconStyle={{ color: 'var(--color-accent)' }}
                            description="account ID"
                        >
                            {account.external_id}
                        </CopyToClipboardInline>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Tags',
            key: 'tags',
            dataIndex: 'tags',
            render: (_, account) =>
                account.tags && account.tags.length > 0 ? (
                    <ObjectTags tags={account.tags} staticOnly />
                ) : (
                    <span className="text-muted">—</span>
                ),
        },
        {
            title: 'Notebooks',
            key: 'notebooks',
            dataIndex: 'notebooks',
            render: (_, account) => {
                const count = account.notebooks?.length ?? 0
                return count > 0 ? <span>{count}</span> : <span className="text-muted">—</span>
            },
        },
        {
            title: 'CSM',
            key: 'csm',
            render: (_, account) => <AssigneeCell assignment={account.properties?.csm ?? null} />,
        },
        {
            title: 'Account executive',
            key: 'account_executive',
            render: (_, account) => <AssigneeCell assignment={account.properties?.account_executive ?? null} />,
        },
        {
            title: 'Account owner',
            key: 'account_owner',
            render: (_, account) => <AssigneeCell assignment={account.properties?.account_owner ?? null} />,
        },
    ]

    return (
        <LemonTable<AccountApi>
            dataSource={results}
            rowKey="id"
            loading={accountsLoading}
            columns={columns}
            pagination={{
                controlled: true,
                currentPage,
                pageSize: ACCOUNTS_PAGE_SIZE,
                entryCount: totalCount,
                onBackward: () => setCurrentPage(Math.max(1, currentPage - 1)),
                onForward: () => setCurrentPage(currentPage + 1),
            }}
        />
    )
}

function AssigneeCell({ assignment }: { assignment: AccountAssignment }): JSX.Element {
    if (!assignment) {
        return <span className="text-muted">Unassigned</span>
    }
    return (
        <div className="flex items-center gap-2">
            <ProfilePicture user={{ email: assignment.email }} size="sm" />
            <span className="text-sm">{assignment.email}</span>
        </div>
    )
}
