import { CSSTransition } from 'react-transition-group'
import clsx from 'clsx'
import { useValues } from 'kea'

import {
    InsightEditorFilterGroup,
    InsightEditorFilter,
    EditorFilterProps,
    ChartDisplayType,
    AvailableFeature,
    PathType,
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
import { PathsEventsTypes } from 'scenes/insights/EditorFilters/PathsEventTypes'
import { PathsTargetEnd, PathsTargetStart } from 'scenes/insights/EditorFilters/PathsTarget'
import { PathsExclusions } from 'scenes/insights/EditorFilters/PathsExclusions'
import { PathsWildcardGroups } from 'scenes/insights/EditorFilters/PathsWildcardGroups'
import { PathsAdvanced } from 'scenes/insights/EditorFilters/PathsAdvanced'
import { FunnelsQuerySteps } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { Attribution } from 'scenes/insights/EditorFilters/AttributionFilter'
import { FunnelsAdvanced } from 'scenes/insights/EditorFilters/FunnelsAdvanced'
import { RetentionSummary } from 'scenes/insights/EditorFilters/RetentionSummary'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import './EditorFilters.scss'
import { PathsHogQL } from 'scenes/insights/EditorFilters/PathsHogQL'

export interface EditorFiltersProps {
    query: InsightQueryNode
    showing: boolean
    embedded: boolean
}

export function EditorFilters({ query, showing, embedded }: EditorFiltersProps): JSX.Element | null {
    const { user } = useValues(userLogic)
    const availableFeatures = user?.organization?.available_features || []

    const { insight, insightProps } = useValues(insightLogic)
    const {
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isLifecycle,
        isTrendsLike,
        display,
        breakdown,
        pathsFilter,
        querySource,
    } = useValues(insightVizDataLogic(insightProps))
    const { isStepsFunnel } = useValues(funnelDataLogic(insightProps))

    if (!querySource) {
        return null
    }

    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)) ||
        isStepsFunnel
    const hasPathsAdvanced = availableFeatures.includes(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution = isStepsFunnel
    const hasPathsHogQL = isPaths && pathsFilter?.include_event_types?.includes(PathType.HogQL)

    const editorFilters: InsightEditorFilterGroup[] = [
        {
            title: 'General',
            editorFilters: filterFalsy([
                isRetention && {
                    key: 'retention-summary',
                    label: 'Retention Summary',
                    component: RetentionSummary,
                },
                ...(isPaths
                    ? filterFalsy([
                          {
                              key: 'event-types',
                              label: 'Event Types',
                              component: PathsEventsTypes,
                          },
                          hasPathsHogQL && {
                              key: 'hogql',
                              label: 'HogQL Expression',
                              component: PathsHogQL,
                          },
                          hasPathsAdvanced && {
                              key: 'wildcard-groups',
                              label: 'Wildcard Groups',
                              showOptional: true,
                              component: PathsWildcardGroups,
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
                              component: PathsTargetStart,
                          },
                          hasPathsAdvanced && {
                              key: 'ends-target',
                              label: 'Ends at',
                              component: PathsTargetEnd,
                          },
                      ])
                    : []),
                ...(isFunnels
                    ? filterFalsy([
                          {
                              key: 'query-steps',
                              component: FunnelsQuerySteps,
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
            editorFilters: filterFalsy([
                isLifecycle
                    ? {
                          key: 'toggles',
                          label: 'Lifecycle Toggles',
                          position: 'right',
                          component: LifecycleToggles as (props: EditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                {
                    key: 'properties',
                    label: 'Filters',
                    position: 'right',
                    component: GlobalAndOrFilters as (props: EditorFilterProps) => JSX.Element | null,
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
                                  When breaking funnels down by a property, you can choose how to assign users to the
                                  various property values. This is useful because property values can change for a
                                  user/group as someone travels through the funnel.
                                  <ul className="list-disc pl-4 pt-4">
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
                          component: Attribution,
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
                    component: PathsExclusions,
                },
            ]),
        },
        {
            title: 'Advanced Options',
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-advanced',
                    position: 'left',
                    component: PathsAdvanced,
                },
                isFunnels && {
                    key: 'funnels-advanced',
                    position: 'left',
                    component: FunnelsAdvanced,
                },
            ]),
        },
        {
            title: 'Sampling',
            editorFilters: filterFalsy([
                {
                    key: 'sampling',
                    position: 'right',
                    component: SamplingFilter,
                },
            ]),
        },
    ]

    let editorFilterGroups: InsightEditorFilterGroup[] = []

    const leftFilters = editorFilters.reduce(
        (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position !== 'right')),
        [] as InsightEditorFilter[]
    )
    const rightFilters = editorFilters.reduce(
        (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position === 'right')),
        [] as InsightEditorFilter[]
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
                    'EditorFiltersWrapper--embedded': embedded,
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
                        />
                    ))}
                </div>
            </div>
        </CSSTransition>
    )
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
