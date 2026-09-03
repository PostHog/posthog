import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconPeople } from '@posthog/icons'
import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import {
    accountRelatedUsersLogic,
    AccountOrganizationMember,
    PAGE_SIZE,
} from 'products/customer_analytics/frontend/components/Accounts/accountRelatedUsersLogic'
import { AccountsEvents } from 'products/customer_analytics/frontend/components/Accounts/constants'

import { AccountWidgetCard } from './AccountWidgetCard'

interface AccountRelatedPeopleWidgetProps {
    externalId: string | null
    onRemove?: () => void
}

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
        render: (_, member) => <span className="text-secondary truncate">{member.user.email}</span>,
    },
    {
        title: 'Last seen',
        key: 'last_login',
        align: 'right',
        width: 0,
        render: (_, member) => (
            <span className="text-secondary whitespace-nowrap">
                {member.last_login ? <TZLabel time={member.last_login} /> : 'Never'}
            </span>
        ),
    },
]

function RelatedPeopleTable({ externalId }: { externalId: string }): JSX.Element {
    const logic = accountRelatedUsersLogic({ externalId })
    const { membersResponse, membersResponseLoading, page } = useValues(logic)
    const { setPage } = useActions(logic)

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
                useUrl: false,
                entryCount: membersResponse?.count ?? 0,
                onForward: () => setPage(page + 1),
                onBackward: () => setPage(page - 1),
            }}
            emptyState={
                membersResponse === null
                    ? "Couldn't load related people. Try refreshing the page."
                    : 'No people related to this account yet.'
            }
        />
    )
}

function RelatedPeopleMeta({ externalId }: { externalId: string }): JSX.Element | null {
    const { membersResponse } = useValues(accountRelatedUsersLogic({ externalId }))
    if (!membersResponse) {
        return null
    }
    return <span>{`${membersResponse.count} member${membersResponse.count === 1 ? '' : 's'}`}</span>
}

export function AccountRelatedPeopleWidget({ externalId, onRemove }: AccountRelatedPeopleWidgetProps): JSX.Element {
    return (
        <AccountWidgetCard
            icon={<IconPeople />}
            title="Related people"
            meta={externalId ? <RelatedPeopleMeta externalId={externalId} /> : null}
            onRemove={onRemove}
            data-attr="account-related-people-widget"
        >
            {externalId ? (
                <RelatedPeopleTable externalId={externalId} />
            ) : (
                <p className="text-sm text-secondary p-3 mb-0">
                    This account has no external ID, so it cannot be matched to an organization.
                </p>
            )}
        </AccountWidgetCard>
    )
}
