import { Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { PropertyDefinitionUsedInResponseApi } from '~/generated/core/api.schemas'
import { InsightShortId } from '~/types'

interface UsedInSection {
    title: string
    block: { total: number; has_more: boolean; results: unknown[] }
    items: { key: string; url: string; label: string }[]
}

export function PropertyDefinitionUsedIn({
    usedIn,
    loading,
}: {
    usedIn: PropertyDefinitionUsedInResponseApi | null
    loading: boolean
}): JSX.Element {
    if (loading && !usedIn) {
        return <Spinner />
    }
    if (!usedIn) {
        return <span className="text-secondary">Couldn't load usage. Refresh the page to try again.</span>
    }

    const sections: UsedInSection[] = [
        {
            title: 'Insights',
            block: usedIn.insights,
            items: usedIn.insights.results.map((insight) => ({
                key: `insight-${insight.id}`,
                url: urls.insightView(insight.short_id as InsightShortId),
                label: insight.name,
            })),
        },
        {
            title: 'Cohorts',
            block: usedIn.cohorts,
            items: usedIn.cohorts.results.map((cohort) => ({
                key: `cohort-${cohort.id}`,
                url: urls.cohort(cohort.id),
                label: cohort.name || 'Unnamed',
            })),
        },
        {
            title: 'Feature flags',
            block: usedIn.feature_flags,
            items: usedIn.feature_flags.results.map((flag) => ({
                key: `flag-${flag.id}`,
                url: urls.featureFlag(flag.id),
                label: flag.name || flag.key,
            })),
        },
        {
            title: 'Experiments',
            block: usedIn.experiments,
            items: usedIn.experiments.results.map((experiment) => ({
                key: `experiment-${experiment.id}`,
                url: urls.experiment(experiment.id),
                label: experiment.name || 'Unnamed',
            })),
        },
        {
            title: 'Surveys',
            block: usedIn.surveys,
            items: usedIn.surveys.results.map((survey) => ({
                key: `survey-${survey.id}`,
                url: urls.survey(survey.id),
                label: survey.name || 'Unnamed',
            })),
        },
        {
            title: 'Destinations',
            block: usedIn.hog_functions,
            items: usedIn.hog_functions.results.map((fn) => ({
                key: `hog-function-${fn.id}`,
                url: urls.hogFunction(fn.id),
                label: fn.name || 'Unnamed',
            })),
        },
        {
            title: 'Workflows',
            block: usedIn.hog_flows,
            items: usedIn.hog_flows.results.map((flow) => ({
                key: `workflow-${flow.id}`,
                url: urls.workflow(flow.id, 'workflow'),
                label: flow.name || 'Unnamed',
            })),
        },
    ].filter((section) => section.items.length > 0)

    if (sections.length === 0) {
        return (
            <span className="text-secondary">
                This property isn't referenced by any saved insights, cohorts, feature flags, experiments, surveys,
                destinations, or workflows. If you no longer send it, it may be safe to clean up.
            </span>
        )
    }

    return (
        <div className="flex flex-wrap gap-x-12 gap-y-4">
            {sections.map(({ title, block, items }) => (
                <div key={title} className="min-w-48">
                    <h5 className="text-xs font-semibold uppercase opacity-60 mb-0">
                        {title}
                        {block.has_more ? ` (${block.results.length} of ${block.total} shown)` : ` (${block.total})`}
                    </h5>
                    <ul className="list-disc pl-4 mb-0 space-y-0.5">
                        {items.map(({ key, url, label }) => (
                            <li key={key}>
                                <Link to={url}>{label}</Link>
                            </li>
                        ))}
                    </ul>
                </div>
            ))}
        </div>
    )
}
