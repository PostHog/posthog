import { CSSTransition } from 'react-transition-group'
import clsx from 'clsx'
import { useValues } from 'kea'

import {
    QueryInsightEditorFilterGroup,
    QueryInsightEditorFilter,
    QueryEditorFilterProps,
    ChartDisplayType,
    AvailableFeature,
    FunnelVizType,
} from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS, NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'
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
import { getBreakdown, getDisplay } from './utils'
import { PathsEventsTypesDataExploration } from 'scenes/insights/EditorFilters/PathsEventTypes'
import {
    PathsTargetEndDataExploration,
    PathsTargetStartDataExploration,
} from 'scenes/insights/EditorFilters/PathsTarget'
import { PathsExclusionsDataExploration } from 'scenes/insights/EditorFilters/PathsExclusions'
import { PathsWildcardGroupsDataExploration } from 'scenes/insights/EditorFilters/PathsWildcardGroups'
import { PathsAdvancedDataExploration } from 'scenes/insights/EditorFilters/PathsAdvanced'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

export interface EditorFiltersProps {
    query: InsightQueryNode
    setQuery: (node: InsightQueryNode) => void
}

export function EditorFilters({ query, setQuery }: EditorFiltersProps): JSX.Element {
    const { user } = useValues(userLogic)
    const availableFeatures = user?.organization?.available_features || []
    const { insight, insightProps, filterPropertiesCount } = useValues(insightLogic)
    // const { advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))
    const advancedOptionsUsedCount = 0

    const showFilters = true // TODO: implement with insightVizLogic

    const { featureFlags } = useValues(featureFlagLogic)

    const isTrends = isTrendsQuery(query)
    const isFunnels = isFunnelsQuery(query)
    const isRetention = isRetentionQuery(query)
    const isPaths = isPathsQuery(query)
    const isStickiness = isStickinessQuery(query)
    const isLifecycle = isLifecycleQuery(query)

    const display = getDisplay(query)
    const breakdown = getBreakdown(query)

    const isTrendsLike = isTrends || isLifecycle || isStickiness
    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)) ||
        (isRetention &&
            featureFlags[FEATURE_FLAGS.RETENTION_BREAKDOWN] &&
            display !== ChartDisplayType.ActionsLineGraph) ||
        (isFunnels && query.funnelsFilter?.funnel_viz_type === FunnelVizType.Steps)
    const hasPropertyFilters = isTrends || isStickiness || isRetention || isPaths || isFunnels
    const hasPathsAdvanced = availableFeatures.includes(AvailableFeature.PATHS_ADVANCED)

    const editorFilters: QueryInsightEditorFilterGroup[] = [
        {
            title: 'General',
            editorFilters: filterFalsy([
                ...(isPaths
                    ? filterFalsy([
                          {
                              key: 'event-types',
                              label: 'Event Types',
                              component: PathsEventsTypesDataExploration,
                          },
                          hasPathsAdvanced && {
                              key: 'wildcard-groups',
                              label: 'Wildcard Groups',
                              showOptional: true,
                              component: PathsWildcardGroupsDataExploration,
                              tooltip: (
                                  <>
                                      Use wildcard matching to group events by unique values in path item names. Use an
                                      asterisk (*) in place of unique values. For example, instead of
                                      /merchant/1234/payment, replace the unique value with an asterisk
                                      /merchant/*/payment. <b>Use a comma to separate multiple wildcards.</b>
                                  </>
                              ),
                          },
                          {
                              key: 'start-target',
                              label: 'Starts at',
                              component: PathsTargetStartDataExploration,
                          },
                          hasPathsAdvanced && {
                              key: 'ends-target',
                              label: 'Ends at',
                              component: PathsTargetEndDataExploration,
                          },
                      ])
                    : []),
            ]),
        },
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
            count: breakdown?.breakdowns?.length || (breakdown?.breakdown ? 1 : 0),
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
        {
            title: 'Exclusions',
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-exclusions',
                    label: 'Exclusions',
                    position: 'right',
                    tooltip: (
                        <>Exclude events from Paths visualisation. You can use wildcard groups in exclusions as well.</>
                    ),
                    component: PathsExclusionsDataExploration,
                },
            ]),
        },
        {
            title: 'Advanced Options',
            defaultExpanded: !!advancedOptionsUsedCount,
            count: advancedOptionsUsedCount,
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-advanced',
                    component: (props) => (
                        <PayGateMini feature={AvailableFeature.PATHS_ADVANCED}>
                            <PathsAdvancedDataExploration {...props} />
                        </PayGateMini>
                    ),
                },
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
