import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconCalendar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dateMapping } from 'lib/utils/dateFilters'
import { isDashboardFilterEmpty } from 'scenes/dashboard/dashboardFilterEmpty'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { HogQLQuery, Node } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { ItemMode } from '~/types'

const FILTERS_PLACEHOLDER = /\{\s*filters\b/

const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.SessionProperties,
    TaxonomicFilterGroupType.HogQLExpression,
]

function hogQLSource(query: Node | null): HogQLQuery | null {
    const source = isDataVisualizationNode(query) || isDataTableNode(query) ? query.source : query
    return isHogQLQuery(source) ? source : null
}

interface SqlInsightFilterOverridesProps {
    query: Node | null
    children: ReactNode
}

/**
 * View-time filter controls for saved SQL insights whose query uses the `{filters}` placeholder.
 * Renders the results inside the classic insight card, with a date filter and property filters in
 * the header row. Changes are written to the `filters_override` URL param (the same mechanism
 * dashboards use to override tiles), applied server-side into `{filters}` — the saved insight is
 * never modified. An override date range replaces the saved one; override properties are appended.
 */
export function SqlInsightFilterOverrides({ query, children }: SqlInsightFilterOverridesProps): JSX.Element {
    const { insightId, insightMode, filtersOverride } = useValues(insightSceneLogic)
    const { updateFiltersOverride } = useActions(insightSceneLogic)

    const source = hogQLSource(query)
    if (
        insightMode !== ItemMode.View ||
        !insightId ||
        insightId === 'new' ||
        insightId.startsWith('new-') ||
        !source ||
        !FILTERS_PLACEHOLDER.test(source.query)
    ) {
        return <>{children}</>
    }

    const overrides = filtersOverride ?? {}
    const saved = source.filters ?? {}

    return (
        <div
            className="InsightVizDisplay InsightVizDisplay--type-trends border rounded bg-surface-primary"
            data-attr="sql-insight-filter-overrides"
        >
            {/* Mirrors InsightDisplayConfig's markup so the header matches classic insights */}
            <div className="InsightDisplayConfig @container flex justify-between items-center flex-wrap gap-2 [&_.LemonButton--small]:[--lemon-button-gap:0.25rem] [&_.LemonButton--small]:[--lemon-button-padding-horizontal:0.375rem]">
                <div className="flex items-center gap-x-2 flex-wrap gap-y-2">
                    <span className="flex items-center gap-x-2 text-sm">
                        <DateFilter
                            showExplicitDateToggle
                            allowTimePrecision
                            allowFixedRangeWithTime
                            dateFrom={overrides.date_from ?? saved.dateRange?.date_from ?? null}
                            dateTo={overrides.date_to ?? saved.dateRange?.date_to ?? null}
                            explicitDate={overrides.explicitDate ?? saved.dateRange?.explicitDate ?? false}
                            onChange={(date_from, date_to, explicitDate) =>
                                updateFiltersOverride({ ...overrides, date_from, date_to, explicitDate })
                            }
                            dateOptions={dateMapping}
                            allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
                            makeLabel={(key) => (
                                <>
                                    <IconCalendar /> {key}
                                </>
                            )}
                        />
                    </span>
                    <span className="flex items-center gap-x-2 text-sm">
                        <PropertyFilters
                            pageKey={`sql-insight-filter-overrides-${insightId}`}
                            buttonSize="small"
                            propertyFilters={overrides.properties ?? []}
                            onChange={(properties) => updateFiltersOverride({ ...overrides, properties })}
                            taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                            addText="Add filter"
                        />
                    </span>
                </div>
                {!isDashboardFilterEmpty(filtersOverride) && (
                    <div className="flex items-center gap-x-2">
                        <LemonButton size="small" onClick={() => updateFiltersOverride(null)}>
                            Reset to saved
                        </LemonButton>
                    </div>
                )}
            </div>
            <div className="InsightVizDisplay__content">{children}</div>
        </div>
    )
}
