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
    /** Uses the caller cannot view. They count toward the total but never appear in the items. */
    hidden?: number
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
    // Every flag that is not archived blocks a delete, enabled or not, so the blocking list drops the
    // archived ones and counts what is left instead of the server's total.
    const flags = blockingOnly
        ? usedIn.feature_flags.results.filter((flag) => !flag.archived)
        : usedIn.feature_flags.results
    // The editor lists what the caller can view. Only the blocking list counts hidden uses, because
    // they still stop a delete.
    const hiddenIn = (block: { hidden?: number }): number => (blockingOnly ? (block.hidden ?? 0) : 0)
    const hiddenFlags = hiddenIn(usedIn.feature_flags)
    const hiddenInsights = hiddenIn(usedIn.insights)
    const hiddenCohorts = hiddenIn(usedIn.cohorts)
    // During a rollout the frontend can reach a backend that predates these blocks.
    const environments = usedIn.test_account_filters?.results ?? []
    const workflows = usedIn.workflows ?? { results: [], total: 0, hidden: 0, has_more: false }

    const sections: CohortUsedInSection[] = [
        {
            title: 'Feature flags',
            noun: 'feature flag',
            total: (blockingOnly ? flags.length : usedIn.feature_flags.total) + hiddenFlags,
            hidden: hiddenFlags,
            items: flags.map((flag) => ({
                key: `flag-${flag.id}`,
                url: urls.featureFlag(flag.id),
                label: flag.name || flag.key,
            })),
        },
        {
            title: 'Insights',
            noun: 'insight',
            total: usedIn.insights.total + hiddenInsights,
            hidden: hiddenInsights,
            items: usedIn.insights.results.map((insight) => ({
                key: `insight-${insight.id}`,
                url: urls.insightView(insight.short_id as InsightShortId),
                label: insight.name,
            })),
        },
        {
            title: 'Cohorts',
            noun: 'cohort',
            total: usedIn.cohorts.total + hiddenCohorts,
            hidden: hiddenCohorts,
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
    ]
    // The editor shows workflows in its own link next to the cohort type, so only the blocking list includes them.
    // Every workflow in the block is active, and an active workflow blocks a delete.
    if (blockingOnly) {
        sections.push({
            title: 'Workflows',
            noun: 'workflow',
            total: workflows.total,
            hidden: workflows.hidden,
            items: workflows.results.map((workflow) => ({
                key: `workflow-${workflow.id}`,
                url: urls.workflow(workflow.id, 'workflow'),
                label: workflow.name || 'Untitled workflow',
            })),
        })
    }
    // A section whose uses are all hidden from the caller has no items, but it still blocks a delete.
    return sections.filter((section) => section.total > 0)
}
