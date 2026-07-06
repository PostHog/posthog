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

// Outcomes: a null `sfdcId` means the account isn't linked to Salesforce; `opportunities` is null when the
// query couldn't run (the data warehouse table only exists in production), as opposed to an empty array
// (linked account with no opportunities). `loadFailed` is set when the load itself errored (e.g. the
// account fetch failed) — the view shows a "couldn't load" state rather than hanging on the skeleton.
export interface AccountOpportunitiesResult {
    sfdcId: string | null
    opportunities: AccountOpportunity[] | null
    loadFailed?: boolean
}

// Identity used as a "not loaded yet" sentinel by the view — every loaded outcome returns a fresh object.
export const NOT_LOADED: AccountOpportunitiesResult = { sfdcId: null, opportunities: null }

const OPPORTUNITY_TABLE = 'salesforce.opportunity'

const isExpectedMissingTableError = (error: unknown): boolean => {
    const message = error instanceof Error ? error.message : String(error ?? '')
    return (
        message.includes(OPPORTUNITY_TABLE) &&
        (message.includes("don't have access to table") || message.includes('Unknown table'))
    )
}

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
                    let sfdcId: string | null
                    try {
                        const account = await accountsRetrieve(String(values.currentTeamId), props.accountId)
                        sfdcId = account.properties?.sfdc_id ?? null
                    } catch (error) {
                        posthog.captureException(error as Error, {
                            scope: 'accountOpportunitiesLogic.loadOpportunities',
                        })
                        return { sfdcId: null, opportunities: null, loadFailed: true }
                    }
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
                        if (!isExpectedMissingTableError(error)) {
                            posthog.captureException(error as Error, {
                                scope: 'accountOpportunitiesLogic.loadOpportunities',
                            })
                        }
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
