import './EditorFilters.scss'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'
import { CSSTransition } from 'react-transition-group'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { Attribution } from 'scenes/insights/EditorFilters/AttributionFilter'
import { FunnelsAdvanced } from 'scenes/insights/EditorFilters/FunnelsAdvanced'
import { FunnelsQuerySteps } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { PathsAdvanced } from 'scenes/insights/EditorFilters/PathsAdvanced'
import { PathsEventsTypes } from 'scenes/insights/EditorFilters/PathsEventTypes'
import { PathsExclusions } from 'scenes/insights/EditorFilters/PathsExclusions'
import { PathsHogQL } from 'scenes/insights/EditorFilters/PathsHogQL'
import { PathsTargetEnd, PathsTargetStart } from 'scenes/insights/EditorFilters/PathsTarget'
import { PathsWildcardGroups } from 'scenes/insights/EditorFilters/PathsWildcardGroups'
import { RetentionSummary } from 'scenes/insights/EditorFilters/RetentionSummary'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { userLogic } from 'scenes/userLogic'

import { StickinessCriteria } from '~/queries/nodes/InsightViz/StickinessCriteria'
import { InsightQueryNode } from '~/queries/schema'
import {
    AvailableFeature,
    ChartDisplayType,
    EditorFilterProps,
    InsightEditorFilter,
    InsightEditorFilterGroup,
    PathType,
} from '~/types'

import { Breakdown } from './Breakdown'
import { EditorFilterGroup } from './EditorFilterGroup'
import { GlobalAndOrFilters } from './GlobalAndOrFilters'
import { LifecycleToggles } from './LifecycleToggles'
import { TrendsFormula } from './TrendsFormula'
import { TrendsSeries } from './TrendsSeries'
import { TrendsSeriesLabel } from './TrendsSeriesLabel'

export interface EditorFiltersProps {
    query: InsightQueryNode
    showing: boolean
    embedded: boolean
}

export function EditorFilters({ query, showing, embedded }: EditorFiltersProps): JSX.Element | null {
    const { hasAvailableFeature } = useValues(userLogic)

    const { insightProps } = useValues(insightLogic)
    const {
        isTrends,
        isFunnels,
        isRetention,
        isPaths,
        isLifecycle,
        isStickiness,
        isTrendsLike,
        display,
        breakdownFilter,
        pathsFilter,
        querySource,
        shouldShowSessionAnalysisWarning,
        hasFormula,
    } = useValues(insightVizDataLogic(insightProps))
    const { isStepsFunnel, isTrendsFunnel } = useValues(funnelDataLogic(insightProps))

    if (!querySource) {
        return null
    }

    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)) ||
        isStepsFunnel ||
        isTrendsFunnel
    const hasPathsAdvanced = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution = isStepsFunnel
    const hasPathsHogQL = isPaths && pathsFilter?.includeEventTypes?.includes(PathType.HogQL)

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
                isTrends && hasFormula
                    ? {
                          key: 'formula',
                          label: 'Formula',
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
                isStickiness
                    ? {
                          key: 'stickinessCriteria',
                          label: () => (
                              <div className="flex">
                                  <span>Stickiness Criteria</span>
                                  <Tooltip
                                      closeDelayMs={200}
                                      title={
                                          <div className="space-y-2">
                                              <div>
                                                  The stickiness criteria defines how many times a user must perform an
                                                  event inside of a given interval in order to be considered "sticky."
                                              </div>
                                          </div>
                                      }
                                  >
                                      <IconInfo className="text-xl text-muted-alt shrink-0 ml-1" />
                                  </Tooltip>
                              </div>
                          ),
                          position: 'right',
                          component: StickinessCriteria as (props: EditorFilterProps) => JSX.Element | null,
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
            count: breakdownFilter?.breakdowns?.length || (breakdownFilter?.breakdown ? 1 : 0),
            editorFilters: filterFalsy([
                hasBreakdown
                    ? {
                          key: 'breakdown',
                          position: 'right',
                          component: Breakdown,
                      }
                    : null,
                hasAttribution
                    ? {
                          key: 'attribution',
                          label: () => (
                              <div className="flex">
                                  <span>Attribution type</span>
                                  <Tooltip
                                      closeDelayMs={200}
                                      title={
                                          <div className="space-y-2">
                                              <div>
                                                  When breaking down funnels, it's possible that the same properties
                                                  don't exist on every event. For example, if you want to break down by
                                                  browser on a funnel that contains both frontend and backend events.
                                              </div>
                                              <div>
                                                  In this case, you can choose from which step the properties should be
                                                  selected from by modifying the attribution type. There are four modes
                                                  to choose from:
                                              </div>
                                              <ul className="list-disc pl-4">
                                                  <li>
                                                      First touchpoint: the first property value seen in any of the
                                                      steps is chosen.
                                                  </li>
                                                  <li>
                                                      Last touchpoint: the last property value seen from all steps is
                                                      chosen.
                                                  </li>
                                                  <li>
                                                      All steps: the property value must be seen in all steps to be
                                                      considered in the funnel.
                                                  </li>
                                                  <li>
                                                      Specific step: only the property value seen at the selected step
                                                      is chosen.
                                                  </li>
                                              </ul>
                                              <div>
                                                  Read more in the{' '}
                                                  <Link to="https://posthog.com/docs/product-analytics/funnels#attribution-types">
                                                      documentation.
                                                  </Link>
                                              </div>
                                          </div>
                                      }
                                  >
                                      <IconInfo className="text-xl text-muted-alt shrink-0 ml-1" />
                                  </Tooltip>
                              </div>
                          ),
                          position: 'right',
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
                    'EditorFiltersWrapper--embedded': embedded,
                })}
            >
                <div className="EditorFilters">
                    {editorFilterGroups.map((editorFilterGroup) => (
                        <EditorFilterGroup
                            key={editorFilterGroup.title}
                            editorFilterGroup={editorFilterGroup}
                            insightProps={insightProps}
                            query={query}
                        />
                    ))}
                </div>

                {shouldShowSessionAnalysisWarning ? (
                    <LemonBanner type="info" className="mt-2">
                        When using sessions and session properties, events without session IDs will be excluded from the
                        set of results.{' '}
                        <Link to="https://posthog.com/docs/user-guides/sessions">Learn more about sessions.</Link>
                    </LemonBanner>
                ) : null}
            </div>
        </CSSTransition>
    )
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
