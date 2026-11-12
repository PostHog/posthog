import type { AccountsTableRow, DateRange, HogQLQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

interface AccountHogQLContext {
    accountId: string
    externalId?: string
    groupTypeIndex?: number | null
    weekStartDay?: number
    weeks: number
}

interface BookHogQLContext {
    accounts: AccountsTableRow[]
    dateRange: DateRange
    groupTypeIndex?: number | null
}

export function getActivityHogQLBindings(
    context: AccountHogQLContext | BookHogQLContext
): Pick<HogQLQuery, 'values' | 'filters'> {
    const singleAccount = 'accountId' in context
    const externalIds = singleAccount
        ? context.externalId
            ? [context.externalId]
            : []
        : context.accounts.flatMap((account) => (account.externalId ? [account.externalId] : []))
    return {
        values: singleAccount
            ? {
                  account_id: context.accountId,
                  account_external_id: context.externalId ?? '',
                  week_start_day: context.weekStartDay ?? 0,
              }
            : { account_ids: context.accounts.map(({ id }) => id), account_external_ids: externalIds },
        filters: {
            dateRange: singleAccount ? { date_from: `-${context.weeks - 1}wStart`, date_to: null } : context.dateRange,
            properties:
                context.groupTypeIndex != null && (!singleAccount || externalIds.length > 0)
                    ? [
                          {
                              type: PropertyFilterType.Event,
                              key: `$group_${context.groupTypeIndex}`,
                              operator: PropertyOperator.Exact,
                              value: externalIds,
                          },
                      ]
                    : [],
        },
    }
}
