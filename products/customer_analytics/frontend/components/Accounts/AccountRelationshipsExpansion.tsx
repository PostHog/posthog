import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { AccountRelationshipApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountRelationshipsLogic } from './accountRelationshipsLogic'

const PAGE_SIZE = 10

export function AccountRelationshipsExpansion({ accountId }: { accountId: string }): JSX.Element {
    const { relationships, relationshipsLoading } = useValues(accountRelationshipsLogic({ accountId }))

    const columns: LemonTableColumns<AccountRelationshipApi> = [
        {
            title: 'Relationship',
            key: 'definition',
            render: (_, relationship) => <span className="font-semibold">{relationship.definition.name}</span>,
        },
        {
            title: 'Assignee',
            key: 'user',
            render: (_, relationship) =>
                relationship.user ? (
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={{ email: relationship.user.email }} size="sm" />
                        <span className="text-sm">{relationship.user.email}</span>
                    </div>
                ) : (
                    <span className="text-muted italic">Deleted user</span>
                ),
        },
        {
            title: 'Started',
            key: 'started_at',
            width: 140,
            render: (_, relationship) => <TZLabel time={relationship.started_at} />,
        },
        {
            title: 'Ended',
            key: 'ended_at',
            width: 140,
            render: (_, relationship) =>
                relationship.ended_at ? (
                    <TZLabel time={relationship.ended_at} />
                ) : (
                    <LemonTag type="success">Current</LemonTag>
                ),
        },
    ]

    return (
        <LemonTable<AccountRelationshipApi>
            size="small"
            embedded
            dataSource={relationships ?? []}
            rowKey="id"
            loading={relationshipsLoading}
            columns={columns}
            pagination={{ pageSize: PAGE_SIZE }}
            emptyState={
                relationships === null ? 'Failed to load relationships.' : 'No assignments on this account yet.'
            }
        />
    )
}
