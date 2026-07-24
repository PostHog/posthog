import { useValues } from 'kea'
import { ReactNode } from 'react'

import { IconCalendar } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils/dateFilters'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { HogQLQuery, Node } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { ItemMode } from '~/types'

const FILTERS_PLACEHOLDER = /\{\s*filters\b/

function hogQLSource(query: Node | null): HogQLQuery | null {
    const source = isDataVisualizationNode(query) || isDataTableNode(query) ? query.source : query
    return isHogQLQuery(source) ? source : null
}

interface SqlInsightFiltersProps {
    query: Node | null
    setQuery: (query: Node) => void
    children: ReactNode
}

/**
 * Date range and property filters for SQL insights whose query uses the `{filters}` placeholder,
 * shown in view mode inside the classic insight card. Edits update the query's `filters` in local
 * state and re-run it — exactly how changing the date on any other saved insight works. The saved
 * insight only changes when the user saves.
 */
export function SqlInsightFilters({ query, setQuery, children }: SqlInsightFiltersProps): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)

    const source = hogQLSource(query)
    if (insightMode !== ItemMode.View || !query || !source || !FILTERS_PLACEHOLDER.test(source.query)) {
        return <>{children}</>
    }

    const setSource = (newSource: HogQLQuery): void => {
        setQuery(isDataVisualizationNode(query) || isDataTableNode(query) ? { ...query, source: newSource } : newSource)
    }

    return (
        <div
            className="InsightVizDisplay InsightVizDisplay--type-trends border rounded bg-surface-primary"
            data-attr="sql-insight-filters"
        >
            {/* Mirrors InsightDisplayConfig's markup so the header matches classic insights */}
            <div className="InsightDisplayConfig @container flex justify-between items-center flex-wrap gap-2 [&_.LemonButton--small]:[--lemon-button-gap:0.25rem] [&_.LemonButton--small]:[--lemon-button-padding-horizontal:0.375rem]">
                <div className="flex items-center gap-x-2 flex-wrap gap-y-2">
                    <span className="flex items-center gap-x-2 text-sm">
                        <DateFilter
                            showExplicitDateToggle
                            allowTimePrecision
                            allowFixedRangeWithTime
                            dateFrom={source.filters?.dateRange?.date_from ?? null}
                            dateTo={source.filters?.dateRange?.date_to ?? null}
                            explicitDate={source.filters?.dateRange?.explicitDate ?? false}
                            onChange={(date_from, date_to, explicitDate) =>
                                setSource({
                                    ...source,
                                    filters: { ...source.filters, dateRange: { date_from, date_to, explicitDate } },
                                })
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
                        <EventPropertyFilters query={source} setQuery={setSource} />
                    </span>
                </div>
            </div>
            <div className="InsightVizDisplay__content">{children}</div>
        </div>
    )
}
