import { useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconPeople } from '@posthog/icons'
import { LemonBadge, LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { getUserAdminUrl } from 'lib/utils/userAdmin'
import { urls } from 'scenes/urls'

import { renderColumn } from '~/queries/nodes/DataTable/renderColumn'
import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { ActorsQuery } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { accountMemberAdminLinksLogic } from './accountMemberAdminLinksLogic'
import { accountUsersTableLogic, IMPERSONATE_COLUMN, MEMBERSHIP_COLUMN } from './accountUsersTableLogic'
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
    const { query, exportQuery, memberships } = useValues(logic)
    const { setQuery } = useActions(logic)
    useMountedLogic(accountMemberAdminLinksLogic({ externalId }))

    const context: QueryContext = useMemo(() => {
        const select = (query.source as ActorsQuery).select ?? []
        const identityColumn = select.find((column) =>
            [
                'person_display_name',
                'person',
                'properties.email',
                'properties.name',
                'properties.$name',
                'distinct_id',
            ].includes(removeExpressionComment(column))
        )
        return {
            dataNodeLogicKey: `account-users-${accountId}-${tileProps.instanceId ?? 'default'}`,
            columns: {
                ...(identityColumn
                    ? {
                          [identityColumn]: {
                              render: ({ value, record, recordIndex, rowCount }) => {
                                  const personId = Array.isArray(record)
                                      ? record[select.indexOf(MEMBERSHIP_COLUMN)]
                                      : undefined
                                  const accounts = memberships?.[String(personId)]?.accounts
                                  const identity = renderColumn(
                                      identityColumn,
                                      value,
                                      record as any[],
                                      recordIndex,
                                      rowCount,
                                      query,
                                      setQuery
                                  )
                                  if (!accounts || accounts.length < 2) {
                                      return <>{identity}</>
                                  }
                                  return (
                                      <div className="inline-flex items-center gap-2">
                                          {identity}
                                          <Tooltip
                                              interactive
                                              onOpen={() => posthog.capture(AccountsEvents.RelatedUserAccountsViewed)}
                                              title={
                                                  <div>
                                                      <p>
                                                          {`This user belongs to ${accounts.length} accounts you can access, including this account.`}
                                                      </p>
                                                      <div className="font-semibold">Other accounts</div>
                                                      <ul className="list-disc pl-4 max-h-48 overflow-y-auto">
                                                          {accounts
                                                              .filter((account) => account.id !== accountId)
                                                              .map((account) => (
                                                                  <li key={account.id}>
                                                                      <Link
                                                                          to={urls.customerAnalyticsAccount(account.id)}
                                                                          data-attr="customer-analytics-user-other-account-link"
                                                                          onClick={() =>
                                                                              posthog.capture(
                                                                                  AccountsEvents.AccountOpened
                                                                              )
                                                                          }
                                                                      >
                                                                          {account.name}
                                                                      </Link>
                                                                  </li>
                                                              ))}
                                                      </ul>
                                                  </div>
                                              }
                                          >
                                              <span
                                                  tabIndex={0}
                                                  aria-label={`Belongs to ${accounts.length} accounts`}
                                                  className="relative inline-flex shrink-0 items-center m-1 text-secondary"
                                              >
                                                  <IconPeople className="text-xl" />
                                                  <LemonBadge.Number
                                                      count={accounts.length}
                                                      size="xsmall"
                                                      position="top-right"
                                                  />
                                              </span>
                                          </Tooltip>
                                      </div>
                                  )
                              },
                          },
                      }
                    : {}),
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
        }
    }, [externalId, exportQuery, accountId, tileProps.instanceId, memberships, query, setQuery])

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
