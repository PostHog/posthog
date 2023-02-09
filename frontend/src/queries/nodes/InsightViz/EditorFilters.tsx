import { CSSTransition } from 'react-transition-group'
import clsx from 'clsx'
import { useValues } from 'kea'

import {
    QueryInsightEditorFilterGroup,
    QueryInsightEditorFilter,
    QueryEditorFilterProps,
    ChartDisplayType,
    AvailableFeature,
} from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'

import { InsightQueryNode } from '~/queries/schema'
import { EditorFilterGroup } from './EditorFilterGroup'
import { LifecycleToggles } from './LifecycleToggles'
import { GlobalAndOrFilters } from './GlobalAndOrFilters'
import { TrendsSeries } from './TrendsSeries'
import { TrendsSeriesLabel } from './TrendsSeriesLabel'
import { TrendsFormulaLabel } from './TrendsFormulaLabel'
import { TrendsFormula } from './TrendsFormula'
import { Breakdown } from './Breakdown'
import { PathsEventsTypesDataExploration } from 'scenes/insights/EditorFilters/PathsEventTypes'
import {
    PathsTargetEndDataExploration,
    PathsTargetStartDataExploration,
} from 'scenes/insights/EditorFilters/PathsTarget'
import { PathsExclusionsDataExploration } from 'scenes/insights/EditorFilters/PathsExclusions'
import { PathsWildcardGroupsDataExploration } from 'scenes/insights/EditorFilters/PathsWildcardGroups'
import { PathsAdvancedDataExploration } from 'scenes/insights/EditorFilters/PathsAdvanced'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FunnelsQueryStepsDataExploration } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { AttributionDataExploration } from 'scenes/insights/EditorFilters/AttributionFilter'
import { FunnelsAdvancedDataExploration } from 'scenes/insights/EditorFilters/FunnelsAdvanced'
import { RetentionSummaryDataExploration } from 'scenes/insights/EditorFilters/RetentionSummary'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
export interface EditorFiltersProps {
    query: InsightQueryNode
    setQuery: (node: InsightQueryNode) => void
    showing: boolean
}

export function EditorFilters({ query, setQuery, showing }: EditorFiltersProps): JSX.Element {
    const { user } = useValues(userLogic)
    const availableFeatures = user?.organization?.available_features || []

    const { insight, insightProps, filterPropertiesCount } = useValues(insightLogic)
    const { isTrends, isFunnels, isRetention, isPaths, isLifecycle, isTrendsLike, display, breakdown } = useValues(
        insightDataLogic(insightProps)
    )
    const { isStepsFunnel } = useValues(funnelDataLogic(insightProps))

    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)) ||
        isStepsFunnel
    const hasPathsAdvanced = availableFeatures.includes(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution = isStepsFunnel

    const editorFilters: QueryInsightEditorFilterGroup[] = [
        {
            title: 'General',
            editorFilters: filterFalsy([
                isRetention && {
                    key: 'retention-summary',
                    label: 'Retention Summary',
                    component: RetentionSummaryDataExploration,
                },
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
                ...(isFunnels
                    ? filterFalsy([
                          {
                              key: 'query-steps',
                              component: FunnelsQueryStepsDataExploration,
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
                          key: 'toggles',
                          label: 'Lifecycle Toggles',
                          position: 'right',
                          component: LifecycleToggles as (props: QueryEditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                {
                    key: 'properties',
                    label: 'Filters',
                    position: 'right',
                    component: GlobalAndOrFilters as (props: QueryEditorFilterProps) => JSX.Element | null,
                },
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
                hasAttribution
                    ? {
                          key: 'attribution',
                          label: 'Attribution type',
                          position: 'right',
                          tooltip: (
                              <div>
                                  Attribution type determines which property value to use for the entire funnel.
                                  <ul className="list-disc pl-4">
                                      <li>First step: the first property value seen from all steps is chosen.</li>
                                      <li>Last step: last property value seen from all steps is chosen.</li>
                                      <li>Specific step: the property value seen at that specific step is chosen.</li>
                                      <li>All steps: the property value must be seen in all steps.</li>
                                      <li>
                                          Any step: the property value must be seen on at least one step of the funnel.
                                      </li>
                                  </ul>
                              </div>
                          ),
                          component: AttributionDataExploration,
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
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-advanced',
                    position: 'left',
                    component: (props) => (
                        <PayGateMini feature={AvailableFeature.PATHS_ADVANCED}>
                            <PathsAdvancedDataExploration {...props} />
                        </PayGateMini>
                    ),
                },
                isFunnels && {
                    key: 'funnels-advanced',
                    position: 'left',
                    component: FunnelsAdvancedDataExploration,
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
        <CSSTransition in={showing} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
            <div
                className={clsx('EditorFiltersWrapper', {
                    'EditorFiltersWrapper--singlecolumn': isFunnels,
                })}
            >
                <div className="EditorFilters">
                    {(isFunnels ? editorFilters : editorFilterGroups).map((editorFilterGroup) => (
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
