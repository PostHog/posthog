import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { getUserAdminUrl } from 'lib/utils/userAdmin'

import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'

import { accountMemberAdminLinksLogic } from './accountMemberAdminLinksLogic'
import { accountUsersTableLogic, IMPERSONATE_COLUMN } from './accountUsersTableLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'
import { AccountsEvents } from './constants'

function ImpersonateButton({
    externalId,
    distinctIds,
}: {
    externalId: string
    distinctIds: string[]
}): JSX.Element | null {
    const { memberByDistinctId } = useValues(accountMemberAdminLinksLogic({ externalId }))
    // Distinct IDs come from SDK events, so a value like `__proto__` must not resolve to an inherited property.
    const distinctId = distinctIds.find((id) => Object.hasOwn(memberByDistinctId, id))
    if (!distinctId) {
        return null
    }
    const member = memberByDistinctId[distinctId]
    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            to={getUserAdminUrl(member.region, member.user.id)}
            targetBlank
            tooltip="Open this user in admin to impersonate them."
            data-attr="customer-analytics-account-user-admin-link"
            onClick={() => posthog.capture(AccountsEvents.RelatedUserAdminOpened, { region: member.region })}
        >
            Impersonate
        </LemonButton>
    )
}

interface AccountUsersTableProps extends AccountViewTileLogicProps {
    accountId: string
    externalId: string
    embedded?: boolean
}

export function AccountUsersTable({
    accountId,
    externalId,
    embedded = true,
    ...tileProps
}: AccountUsersTableProps): JSX.Element {
    const logic = accountUsersTableLogic({ accountId, ...tileProps })
    const { query, exportQuery } = useValues(logic)
    const { setQuery } = useActions(logic)
    useMountedLogic(accountMemberAdminLinksLogic({ externalId }))

    const context: QueryContext = useMemo(
        () => ({
            columns: {
                [IMPERSONATE_COLUMN]: {
                    title: 'Actions',
                    // A numeric 0 is falsy, so DataTable would ignore it and let the button stretch.
                    width: '0',
                    render: ({ value }) => (
                        <ImpersonateButton externalId={externalId} distinctIds={(value as string[] | null) ?? []} />
                    ),
                },
            },
            dataTableExportQuery: exportQuery,
            dataTableSortOnHeaderClick: true,
        }),
        [externalId, exportQuery]
    )

    return (
        <Query
            uniqueKey={`account-users-${accountId}-${tileProps.instanceId ?? 'default'}`}
            query={{ ...query, embedded }}
            setQuery={setQuery}
            context={context}
            dataAttr="customer-analytics-account-users-table"
        />
    )
}
