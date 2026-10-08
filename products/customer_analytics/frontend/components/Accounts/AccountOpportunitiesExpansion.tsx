import { useValues } from 'kea'
import type { ReactNode } from 'react'

import * as businessEvolutionPng from '@posthog/brand/hoggies/png/business-evolution'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightShortId } from '~/types'

import {
    accountOpportunitiesLogic,
    NOT_LOADED,
    OPPORTUNITIES_INSIGHT_SHORT_ID,
    SALESFORCE_ACCOUNT_VARIABLE,
} from './accountOpportunitiesLogic'

const HedgehogBusiness = pngHoggie(businessEvolutionPng)

function OpportunitiesEmptyState({ title, detail }: { title: string; detail: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center">
            <HedgehogBusiness className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
        </div>
    )
}

export function AccountOpportunitiesExpansion({
    accountId,
    instanceId,
}: {
    accountId: string
    instanceId?: string
}): JSX.Element {
    const logic = accountOpportunitiesLogic({ accountId, instanceId })
    const { opportunitiesResult, opportunitiesResultLoading, variablesOverride } = useValues(logic)

    if (opportunitiesResultLoading || opportunitiesResult === NOT_LOADED) {
        return <LemonSkeleton className="h-64 w-full" />
    }

    const { sfdcId, insight, loadFailed } = opportunitiesResult

    if (loadFailed) {
        return (
            <OpportunitiesEmptyState
                title="Couldn't load opportunities"
                detail="Something went wrong loading this account's opportunities. Try refreshing the page."
            />
        )
    }

    if (!sfdcId) {
        return (
            <OpportunitiesEmptyState
                title="Not linked to Salesforce"
                detail="This account doesn't have a Salesforce ID, so there are no opportunities to show."
            />
        )
    }

    if (!insight?.query) {
        return (
            <OpportunitiesEmptyState
                title="No opportunities insight here"
                detail="We couldn't find the saved opportunities insight in this environment."
            />
        )
    }

    if (!variablesOverride) {
        return (
            <OpportunitiesEmptyState
                title="Opportunities insight needs an account filter"
                detail={
                    <>
                        Add <code>{`{variables.${SALESFORCE_ACCOUNT_VARIABLE}}`}</code> to the SQL of the{' '}
                        <Link to={urls.insightView(OPPORTUNITIES_INSIGHT_SHORT_ID)} target="_blank">
                            saved opportunities insight
                        </Link>
                        , so it shows only this account's opportunities.
                    </>
                }
            />
        )
    }

    const queryKey = `account-opportunities-${accountId}-${instanceId ?? 'default'}`

    return (
        /* Embedded DataVisualization collapses to a sliver without a fixed-height parent (InsightCard__viz is flex:1, min-height:0). */
        <div className="h-80 flex flex-col overflow-hidden">
            <Query
                key={queryKey}
                uniqueKey={queryKey}
                query={insight.query}
                variablesOverride={variablesOverride}
                readOnly
                embedded
                // Attach the insight's data logic to the tab logic, which the expanded-row root keeps mounted,
                // so the loaded results survive tab switches instead of refetching on return.
                attachTo={logic}
                context={{
                    insightProps: {
                        dashboardItemId: queryKey as InsightShortId,
                        dataNodeCollectionId: queryKey,
                    },
                }}
            />
        </div>
    )
}
