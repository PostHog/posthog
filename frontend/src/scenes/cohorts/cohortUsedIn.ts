import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import type { CohortUsedInResponseApi } from 'products/cohorts/frontend/generated/api.schemas'

export interface CohortUsedInItem {
    key: string
    url: string
    label: string
}

export interface CohortUsedInSection {
    title: string
    noun: string
    /** Every use, which can exceed the number of items when the API truncates the list. */
    total: number
    items: CohortUsedInItem[]
}

export interface CohortUsedInSectionsOptions {
    /** Keep only the references that make the server refuse a delete. */
    blockingOnly?: boolean
}

export function cohortUsedInSections(
    usedIn: CohortUsedInResponseApi,
    { blockingOnly = false }: CohortUsedInSectionsOptions = {}
): CohortUsedInSection[] {
    // Only an enabled flag blocks a delete, so the blocking list drops the disabled ones and
    // counts what is left instead of the server's total.
    const flags = blockingOnly
        ? usedIn.feature_flags.results.filter((flag) => flag.active)
        : usedIn.feature_flags.results
    // During a rollout the frontend can reach a backend that predates this block.
    const environments = usedIn.test_account_filters?.results ?? []

    return [
        {
            title: 'Feature flags',
            noun: 'feature flag',
            total: blockingOnly ? flags.length : usedIn.feature_flags.total,
            items: flags.map((flag) => ({
                key: `flag-${flag.id}`,
                url: urls.featureFlag(flag.id),
                label: flag.name || flag.key,
            })),
        },
        {
            title: 'Insights',
            noun: 'insight',
            total: usedIn.insights.total,
            items: usedIn.insights.results.map((insight) => ({
                key: `insight-${insight.id}`,
                url: urls.insightView(insight.short_id as InsightShortId),
                label: insight.name,
            })),
        },
        {
            title: 'Cohorts',
            noun: 'cohort',
            total: usedIn.cohorts.total,
            items: usedIn.cohorts.results.map((cohort) => ({
                key: `cohort-${cohort.id}`,
                url: urls.cohort(cohort.id),
                label: cohort.name,
            })),
        },
        {
            title: 'Filter out internal and test users',
            noun: 'environment',
            total: usedIn.test_account_filters?.total ?? 0,
            items: environments.map((environment) => ({
                key: `environment-${environment.id}`,
                // The setting is per environment, so the link carries the environment it belongs to
                // rather than the one the user is looking at.
                url: addProjectIdIfMissing(
                    urls.settings('environment-customization', 'internal-user-filtering'),
                    environment.id
                ),
                label: environment.name,
            })),
        },
    ].filter((section) => section.items.length > 0)
}
