import { afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import { accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import type { accountOpportunitiesLogicType } from './accountOpportunitiesLogicType'

export interface AccountOpportunitiesLogicProps {
    accountId: string
}

export interface AccountOpportunity {
    id: string
    name: string | null
    totalCreditAmount: number | null
    closeDate: string | null
    contractStartDate: string | null
}

// Three distinct outcomes: a null `sfdcId` means the account isn't linked to Salesforce; `opportunities`
// is null when the query couldn't run (the data warehouse table only exists in production), as opposed to
// an empty array (linked account with no opportunities).
export interface AccountOpportunitiesResult {
    sfdcId: string | null
    opportunities: AccountOpportunity[] | null
}

// Identity used as a "not loaded yet" sentinel by the view — every loaded outcome returns a fresh object.
export const NOT_LOADED: AccountOpportunitiesResult = { sfdcId: null, opportunities: null }

export const accountOpportunitiesLogic = kea<accountOpportunitiesLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountOpportunitiesLogic', key]),
    props({} as AccountOpportunitiesLogicProps),
    key((props) => props.accountId),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ props, values }) => ({
        opportunitiesResult: [
            NOT_LOADED,
            {
                loadOpportunities: async (): Promise<AccountOpportunitiesResult> => {
                    const account = await accountsRetrieve(String(values.currentTeamId), props.accountId)
                    const sfdcId = account.properties?.sfdc_id ?? null
                    if (!sfdcId) {
                        return { sfdcId: null, opportunities: null }
                    }
                    try {
                        const response = (await api.query({
                            kind: NodeKind.HogQLQuery,
                            tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
                            query: hogql`
                                select id, name, total_credit_amount_c, close_date, contract_start_date_c
                                from salesforce.opportunity
                                where account_id = ${sfdcId}
                                order by close_date desc
                                limit 500
                            `,
                        })) as HogQLQueryResponse
                        const rows = (response.results ?? []) as unknown[][]
                        const opportunities: AccountOpportunity[] = rows.map((row) => ({
                            id: String(row[0]),
                            name: (row[1] as string | null) ?? null,
                            totalCreditAmount: (row[2] as number | null) ?? null,
                            closeDate: (row[3] as string | null) ?? null,
                            contractStartDate: (row[4] as string | null) ?? null,
                        }))
                        return { sfdcId, opportunities }
                    } catch (error) {
                        // `salesforce.opportunity` only exists in production. Elsewhere (and on genuine failures,
                        // which we still report) we degrade to the empty state instead of a red query-error box.
                        posthog.captureException(error as Error, {
                            scope: 'accountOpportunitiesLogic.loadOpportunities',
                        })
                        return { sfdcId, opportunities: null }
                    }
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadOpportunities()
    }),
])
