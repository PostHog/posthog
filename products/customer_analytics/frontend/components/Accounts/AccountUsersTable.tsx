import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'

import { getAccountUserAdminSearchUrl, getAccountUserRegion } from './accountRelatedUserAdminUrl'
import { accountUsersTableLogic, IMPERSONATE_COLUMN } from './accountUsersTableLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'
import { AccountsEvents } from './constants'

const QUERY_CONTEXT: QueryContext = {
    columns: {
        [IMPERSONATE_COLUMN]: {
            title: 'Actions',
            render: function ImpersonateButton({ value }) {
                const [email, instanceUrl] = (value as [string | null, string | null] | null) ?? []
                const region = getAccountUserRegion(instanceUrl)
                return (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        to={email ? getAccountUserAdminSearchUrl(region, email) : undefined}
                        targetBlank
                        disabledReason={email ? undefined : 'This person has no email address'}
                        tooltip="Open this user in admin to impersonate them."
                        data-attr="customer-analytics-account-user-admin-link"
                        onClick={() => posthog.capture(AccountsEvents.RelatedUserAdminOpened, { region })}
                    >
                        Impersonate
                    </LemonButton>
                )
            },
        },
    },
    dataTableExportExcludedColumns: [IMPERSONATE_COLUMN],
}

interface AccountUsersTableProps extends AccountViewTileLogicProps {
    accountId: string
    embedded?: boolean
}

export function AccountUsersTable({ accountId, embedded = true, ...tileProps }: AccountUsersTableProps): JSX.Element {
    const logic = accountUsersTableLogic({ accountId, ...tileProps })
    const { query } = useValues(logic)
    const { setQuery } = useActions(logic)

    return (
        <Query
            uniqueKey={`account-users-${accountId}-${tileProps.instanceId ?? 'default'}`}
            query={{ ...query, embedded }}
            setQuery={setQuery}
            context={QUERY_CONTEXT}
            dataAttr="customer-analytics-account-users-table"
        />
    )
}
