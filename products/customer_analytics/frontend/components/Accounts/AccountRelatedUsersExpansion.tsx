import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { accountRelatedUsersLogic, AccountOrganizationMember, PAGE_SIZE } from './accountRelatedUsersLogic'
import { AccountsEvents } from './constants'

export function AccountRelatedUsersExpansion({ externalId }: { externalId: string }): JSX.Element {
    const logic = accountRelatedUsersLogic({ externalId })
    const { membersResponse, membersResponseLoading, page } = useValues(logic)
    const { setPage } = useActions(logic)

    const columns: LemonTableColumns<AccountOrganizationMember> = [
        {
            title: 'User',
            key: 'user',
            render: (_, member) => {
                const name = fullName(member.user) || member.user.email
                return member.user.distinct_id ? (
                    <Link
                        to={urls.personByDistinctId(member.user.distinct_id)}
                        className="font-medium"
                        onClick={() => posthog.capture(AccountsEvents.RelatedUserClicked)}
                    >
                        {name}
                    </Link>
                ) : (
                    <span className="font-medium">{name}</span>
                )
            },
        },
        {
            title: 'Email',
            key: 'email',
            render: (_, member) => <span className="text-sm text-muted">{member.user.email}</span>,
        },
    ]

    return (
        <LemonTable<AccountOrganizationMember>
            size="small"
            embedded
            dataSource={membersResponse?.results ?? []}
            rowKey="id"
            loading={membersResponseLoading}
            columns={columns}
            pagination={{
                controlled: true,
                pageSize: PAGE_SIZE,
                currentPage: page,
                entryCount: membersResponse?.count ?? 0,
                onForward: () => setPage(page + 1),
                onBackward: () => setPage(page - 1),
            }}
            emptyState={
                !externalId
                    ? 'This account has no linked organization.'
                    : membersResponse === null
                      ? 'Failed to load related users.'
                      : 'No users related to this account yet.'
            }
        />
    )
}
