import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton, LemonInput, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { membershipLevelToName } from 'lib/utils/permissioning'
import { capitalizeFirstLetter, fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { getAccountRelatedUserAdminUrl } from './accountRelatedUserAdminUrl'
import { accountRelatedUsersLogic, AccountOrganizationMember, PAGE_SIZE } from './accountRelatedUsersLogic'
import { AccountsEvents } from './constants'

export function AccountRelatedUsersExpansion({ externalId }: { externalId: string }): JSX.Element {
    const logic = accountRelatedUsersLogic({ externalId })
    const { membersResponse, membersResponseLoading, page, searchTerm } = useValues(logic)
    const { user } = useValues(userLogic)
    const { setPage, setSearchTerm } = useActions(logic)

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
        {
            title: 'Access level',
            key: 'level',
            render: (_, member) => capitalizeFirstLetter(membershipLevelToName.get(member.level) ?? 'Unknown'),
        },
    ]

    if (user?.is_staff) {
        columns.push({
            title: 'Actions',
            key: 'actions',
            width: 0,
            render: (_, member) => {
                const adminUrl = getAccountRelatedUserAdminUrl(member.region, member.user.id)

                return (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        to={adminUrl}
                        targetBlank
                        tooltip="Open this user in admin to impersonate them."
                        data-attr="customer-analytics-account-user-admin-link"
                        onClick={() =>
                            posthog.capture(AccountsEvents.RelatedUserAdminOpened, { region: member.region })
                        }
                    >
                        Impersonate
                    </LemonButton>
                )
            },
        })
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                value={searchTerm}
                onChange={setSearchTerm}
                placeholder="Search users by name or email..."
                maxLength={200}
                size="small"
                className="min-w-64"
                data-attr="customer-analytics-account-users-search"
            />
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
                    useUrl: false,
                    entryCount: membersResponse?.count ?? 0,
                    onForward: () => setPage(page + 1),
                    onBackward: () => setPage(page - 1),
                }}
                emptyState={
                    !externalId
                        ? 'This account has no linked organization.'
                        : membersResponse === null
                          ? 'Failed to load related users.'
                          : searchTerm
                            ? 'No users match your search.'
                            : 'No users related to this account yet.'
                }
            />
        </div>
    )
}
