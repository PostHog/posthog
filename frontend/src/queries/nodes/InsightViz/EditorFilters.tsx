import { CSSTransition } from 'react-transition-group'
import clsx from 'clsx'
import { useValues } from 'kea'

import {
    QueryInsightEditorFilterGroup,
    QueryInsightEditorFilter,
    QueryEditorFilterProps,
    ChartDisplayType,
} from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'
import {
    isTrendsQuery,
    isFunnelsQuery,
    isRetentionQuery,
    isPathsQuery,
    isStickinessQuery,
    isLifecycleQuery,
} from '~/queries/utils'

import { InsightQueryNode } from '~/queries/schema'
import { EditorFilterGroup } from './EditorFilterGroup'
import { LifecycleGlobalFilters } from './LifecycleGlobalFilters'
import { LifecycleToggles } from './LifecycleToggles'
import { GlobalAndOrFilters } from './GlobalAndOrFilters'
import { TrendsSeries } from './TrendsSeries'
import { TrendsSeriesLabel } from './TrendsSeriesLabel'
import { TrendsFormulaLabel } from './TrendsFormulaLabel'
import { TrendsFormula } from './TrendsFormula'
import { Breakdown } from './Breakdown'
import { getDisplay } from './utils'

export interface EditorFiltersProps {
    query: InsightQueryNode
    setQuery: (node: InsightQueryNode) => void
}

export function EditorFilters({ query, setQuery }: EditorFiltersProps): JSX.Element {
    const showFilters = true // TODO: implement with insightVizLogic

    const isTrends = isTrendsQuery(query)
    const isFunnels = isFunnelsQuery(query)
    const isRetention = isRetentionQuery(query)
    const isPaths = isPathsQuery(query)
    const isStickiness = isStickinessQuery(query)
    const isLifecycle = isLifecycleQuery(query)

    const display = getDisplay(query)

    const isTrendsLike = isTrends || isLifecycle || isStickiness
    const hasBreakdown = isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)
    // || (isRetention &&
    //     featureFlags[FEATURE_FLAGS.RETENTION_BREAKDOWN] &&
    //     (filters as any).display !== ChartDisplayType.ActionsLineGraph) ||
    // (isFunnels && filters.funnel_viz_type === FunnelVizType.Steps)
    const hasPropertyFilters = isTrends || isStickiness || isRetention || isPaths || isFunnels

    const { insight, insightProps, filterPropertiesCount } = useValues(insightLogic)

    const editorFilters: QueryInsightEditorFilterGroup[] = [
        {
            title: 'Series',
            editorFilters: filterFalsy([
                isTrendsLike && {
                    key: 'series',
                    label: isTrends ? TrendsSeriesLabel : undefined,
                    component: TrendsSeries,
                },
                isTrends
                    ? {
                          key: 'formula',
                          label: TrendsFormulaLabel,
                          component: TrendsFormula,
                      }
                    : null,
            ]),
        },
        {
            title: 'Filters',
            count: filterPropertiesCount,
            editorFilters: filterFalsy([
                isLifecycle
                    ? {
                          key: 'properties',
                          label: 'Filters',
                          position: 'right',
                          component: LifecycleGlobalFilters as (props: QueryEditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                isLifecycle
                    ? {
                          key: 'toggles',
                          label: 'Lifecycle Toggles',
                          position: 'right',
                          component: LifecycleToggles as (props: QueryEditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                hasPropertyFilters
                    ? {
                          key: 'properties',
                          label: 'Filters',
                          position: 'right',
                          component: GlobalAndOrFilters as (props: QueryEditorFilterProps) => JSX.Element | null,
                      }
                    : null,
            ]),
        },
        {
            title: 'Breakdown',
            // count: filters.breakdowns?.length || (filters.breakdown ? 1 : 0),
            position: 'right',
            editorFilters: filterFalsy([
                hasBreakdown
                    ? {
                          key: 'breakdown',
                          label: 'Breakdown by',
                          position: 'right',
                          tooltip: (
                              <>
                                  Use breakdown to see the aggregation (total volume, active users, etc.) for each value
                                  of that property. For example, breaking down by Current URL with total volume will
                                  give you the event volume for each URL your users have visited.
                              </>
                          ),
                          component: Breakdown,
                      }
                    : null,
            ]),
        },
    ]

    let editorFilterGroups: QueryInsightEditorFilterGroup[] = []

    const leftFilters = editorFilters.reduce(
        (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position !== 'right')),
        [] as QueryInsightEditorFilter[]
    )
    const rightFilters = editorFilters.reduce(
        (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position === 'right')),
        [] as QueryInsightEditorFilter[]
    )

    editorFilterGroups = [
        {
            title: 'left',
            editorFilters: leftFilters,
        },
        {
            title: 'right',
            editorFilters: rightFilters,
        },
    ]

    return (
        <CSSTransition in={showFilters} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
            <div
                className={clsx('EditorFiltersWrapper', {
                    'EditorFiltersWrapper--singlecolumn': isFunnels,
                })}
            >
                <div className="EditorFilters">
                    {editorFilterGroups.map((editorFilterGroup) => (
                        <EditorFilterGroup
                            key={editorFilterGroup.title}
                            editorFilterGroup={editorFilterGroup}
                            insight={insight}
                            insightProps={insightProps}
                            query={query}
                            setQuery={setQuery}
                        />
                    ))}
                </div>
            </div>
        </CSSTransition>
    )
}

function filterFalsy(a: (QueryInsightEditorFilter | false | null | undefined)[]): QueryInsightEditorFilter[] {
    return a.filter((e) => !!e) as QueryInsightEditorFilter[]
}
