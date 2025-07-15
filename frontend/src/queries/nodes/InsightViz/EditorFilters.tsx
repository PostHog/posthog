import { IconInfo, IconRefresh, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'
import { objectsEqual } from 'lib/utils'
import { CSSTransition } from 'react-transition-group'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { Attribution } from 'scenes/insights/EditorFilters/AttributionFilter'
import { FunnelsAdvanced } from 'scenes/insights/EditorFilters/FunnelsAdvanced'
import { FunnelsQuerySteps } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { GoalLines } from 'scenes/insights/EditorFilters/GoalLines'
import { PathsAdvanced } from 'scenes/insights/EditorFilters/PathsAdvanced'
import { PathsEventsTypes } from 'scenes/insights/EditorFilters/PathsEventTypes'
import { PathsExclusions } from 'scenes/insights/EditorFilters/PathsExclusions'
import { PathsHogQL } from 'scenes/insights/EditorFilters/PathsHogQL'
import { PathsTargetEnd, PathsTargetStart } from 'scenes/insights/EditorFilters/PathsTarget'
import { PathsWildcardGroups } from 'scenes/insights/EditorFilters/PathsWildcardGroups'
import { PoeFilter } from 'scenes/insights/EditorFilters/PoeFilter'
import { RetentionCondition } from 'scenes/insights/EditorFilters/RetentionCondition'
import { RetentionOptions } from 'scenes/insights/EditorFilters/RetentionOptions'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import MaxTool from 'scenes/max/MaxTool'
import { castAssistantQuery } from 'scenes/max/utils'
import { userLogic } from 'scenes/userLogic'

import { StickinessCriteria } from '~/queries/nodes/InsightViz/StickinessCriteria'
import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from '~/queries/schema/schema-assistant-queries'
import { DataVisualizationNode, InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isHogQLQuery } from '~/queries/utils'
import {
    AvailableFeature,
    ChartDisplayType,
    EditorFilterProps,
    InsightEditorFilter,
    InsightEditorFilterGroup,
    PathType,
} from '~/types'

import { Breakdown } from './Breakdown'
import { CalendarHeatmapFilters } from './CalendarHeatmapFilters'
import { CumulativeStickinessFilter } from './CumulativeStickinessFilter'
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
        isCalendarHeatmap,
        display,
        pathsFilter,
        querySource,
        shouldShowSessionAnalysisWarning,
        hasFormula,
    } = useValues(insightVizDataLogic(insightProps))

    const { handleInsightSuggested, onRejectSuggestedInsight, onReapplySuggestedInsight } = useActions(
        insightLogic(insightProps)
    )
    const { previousQuery, hasRejected, suggestedQuery } = useValues(insightLogic(insightProps))
    const { isStepsFunnel, isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const { setQuery } = useActions(insightVizDataLogic(insightProps))

    const hasScrolled = useRef(false)

    // Count differences between objects
    const countDifferences = useCallback(
        (obj1: any, obj2: any): { count: number; diffs: { key: string; val1: any; val2: any }[] } => {
            let count = 0
            let diffs = []
            const keys = new Set([...Object.keys(obj1 || {}), ...Object.keys(obj2 || {})])

            for (const key of keys) {
                const val1 = obj1?.[key]
                const val2 = obj2?.[key]
                if (Array.isArray(val1) && Array.isArray(val2)) {
                    const val1Set = new Set(val1)
                    const val2Set = new Set(val2)
                    const hasChanged =
                        val1Set.size !== val2Set.size || !Array.from(val1Set).every((item: any) => val2Set.has(item))
                    if (hasChanged) {
                        count += 1
                        diffs.push({ key, val1, val2 })
                    }
                } else if (typeof val1 === 'object' && typeof val2 === 'object' && val1 && val2) {
                    const { count: subCount, diffs: subDiffs } = countDifferences(val1, val2)
                    count += subCount
                    diffs.push(...subDiffs)
                } else if (val1 !== val2) {
                    count += 1
                    diffs.push({ key, val1, val2 })
                }
            }
            return { count, diffs }
        },
        [query, previousQuery]
    )

    // Reset scroll flag when banner disappears
    useEffect(() => {
        if (!previousQuery) {
            hasScrolled.current = false
        }
    }, [previousQuery])

    if (!querySource) {
        return null
    }

    // MaxTool should not be active when insights are embedded (e.g., in notebooks)

    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)) ||
        isStepsFunnel ||
        isTrendsFunnel ||
        isRetention
    const hasPathsAdvanced = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution = isStepsFunnel || isTrendsFunnel
    const hasPathsHogQL = isPaths && pathsFilter?.includeEventTypes?.includes(PathType.HogQL)
    const isLineGraph =
        isTrends &&
        [ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsLineGraphCumulative].includes(
            display || ChartDisplayType.ActionsLineGraph
        )

    const leftEditorFilterGroups: InsightEditorFilterGroup[] = [
        {
            title: 'General',
            editorFilters: filterFalsy([
                ...(isRetention
                    ? [
                          {
                              key: 'retention-condition',
                              label: 'Retention condition',
                              component: RetentionCondition,
                          },
                          {
                              key: 'retention-options',
                              label: 'Calculation options',
                              component: RetentionOptions,
                          },
                      ]
                    : []),
                isFunnels
                    ? {
                          key: 'query-steps',
                          component: FunnelsQuerySteps,
                      }
                    : null,
                ...(isPaths
                    ? [
                          {
                              key: 'event-types',
                              label: 'Event Types',
                              component: PathsEventsTypes,
                          },
                          hasPathsHogQL && {
                              key: 'hogql',
                              label: 'SQL Expression',
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
                      ]
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
                isCalendarHeatmap && {
                    key: 'filters',
                    label: 'Filters',
                    component: CalendarHeatmapFilters,
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
            title: 'Advanced options',
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-advanced',
                    component: PathsAdvanced,
                },
                isFunnels && {
                    key: 'funnels-advanced',
                    component: FunnelsAdvanced,
                },
            ]),
        },
    ]

    const rightEditorFilterGroups: InsightEditorFilterGroup[] = [
        {
            title: 'Filters',
            editorFilters: filterFalsy([
                isLifecycle
                    ? {
                          key: 'toggles',
                          label: 'Lifecycle Toggles',
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
                                          <div className="deprecated-space-y-2">
                                              <div>
                                                  The stickiness criteria defines how many times a user must perform an
                                                  event inside of a given interval in order to be considered "sticky."
                                              </div>
                                          </div>
                                      }
                                  >
                                      <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                                  </Tooltip>
                              </div>
                          ),
                          component: StickinessCriteria as (props: EditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                isStickiness
                    ? {
                          key: 'cumulativeStickiness',
                          label: () => (
                              <div className="flex">
                                  <span>Compute as</span>
                                  <Tooltip
                                      closeDelayMs={200}
                                      title={
                                          <div className="deprecated-space-y-2">
                                              <div>
                                                  Choose how to compute stickiness values. Non-cumulative shows exact
                                                  numbers for each day count, while cumulative shows users active for at
                                                  least that many days.
                                              </div>
                                          </div>
                                      }
                                  >
                                      <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                                  </Tooltip>
                              </div>
                          ),
                          component: CumulativeStickinessFilter as (props: EditorFilterProps) => JSX.Element | null,
                      }
                    : null,
                {
                    key: 'properties',
                    label: 'Filters',
                    component: GlobalAndOrFilters as (props: EditorFilterProps) => JSX.Element | null,
                },
            ]),
        },
        {
            title: 'Breakdown',
            editorFilters: filterFalsy([
                hasBreakdown
                    ? {
                          key: 'breakdown',
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
                                          <div className="deprecated-space-y-2">
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
                                      <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                                  </Tooltip>
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
                    tooltip: (
                        <>Exclude events from Paths visualisation. You can use wildcard groups in exclusions as well.</>
                    ),
                    component: PathsExclusions,
                },
            ]),
        },
        ...(!isCalendarHeatmap
            ? [
                  {
                      title: 'Advanced options',
                      defaultExpanded: false,
                      editorFilters: filterFalsy([
                          {
                              key: 'poe',
                              component: PoeFilter,
                          },
                          {
                              key: 'sampling',
                              component: SamplingFilter,
                          },
                          isTrends &&
                              isLineGraph && {
                                  key: 'goal-lines',
                                  label: 'Goal lines',
                                  tooltip: (
                                      <>
                                          Goal lines can be used to highlight specific goals (Revenue, Signups, etc.) or
                                          limits (Web Vitals, etc.)
                                      </>
                                  ),
                                  component: GoalLines,
                              },
                      ]),
                  },
              ]
            : []),
    ]

    const filterGroupsGroups = [
        { title: 'left', editorFilterGroups: leftEditorFilterGroups.filter((group) => group.editorFilters.length > 0) },
        {
            title: 'right',
            editorFilterGroups: rightEditorFilterGroups.filter((group) => group.editorFilters.length > 0),
        },
    ]

    return (
        <CSSTransition in={showing} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
            <>
                <div>
                    <MaxTool
                        name="create_and_query_insight"
                        displayName="Edit insight"
                        description="Max can tweak and rework the insight you're viewing"
                        context={{
                            current_query: querySource,
                        }}
                        callback={(
                            toolOutput:
                                | AssistantTrendsQuery
                                | AssistantFunnelsQuery
                                | AssistantRetentionQuery
                                | AssistantHogQLQuery
                        ) => {
                            const source = castAssistantQuery(toolOutput)
                            let node: DataVisualizationNode | InsightVizNode
                            if (isHogQLQuery(source)) {
                                node = {
                                    kind: NodeKind.DataVisualizationNode,
                                    source,
                                } satisfies DataVisualizationNode
                            } else {
                                node = { kind: NodeKind.InsightVizNode, source } satisfies InsightVizNode
                            }

                            if (!objectsEqual(node.source, query)) {
                                handleInsightSuggested(node)
                                setQuery(node)
                            }
                        }}
                        initialMaxPrompt="Show me users who "
                        className="EditorFiltersWrapper"
                    >
                        <div>
                            <div
                                className={clsx('flex flex-row flex-wrap gap-8 bg-surface-primary', {
                                    'p-4 rounded border': !embedded,
                                })}
                            >
                                {filterGroupsGroups.map(({ title, editorFilterGroups }) => (
                                    <div key={title} className="flex-1 flex flex-col gap-4 max-w-full">
                                        {editorFilterGroups.map((editorFilterGroup) => (
                                            <EditorFilterGroup
                                                key={editorFilterGroup.title}
                                                editorFilterGroup={editorFilterGroup}
                                                insightProps={insightProps}
                                                query={query}
                                            />
                                        ))}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </MaxTool>

                    {(previousQuery || suggestedQuery) && (
                        <div
                            className="w-full px-2"
                            ref={(el) => {
                                if (el && !hasScrolled.current) {
                                    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
                                    hasScrolled.current = true
                                }
                            }}
                        >
                            <div className="bg-surface-tertiary/80 w-full flex justify-between items-center p-1 pl-2 mx-auto rounded-bl rounded-br">
                                <div className="text-sm text-muted flex items-center gap-2 no-wrap">
                                    <span className="size-2 bg-accent-active rounded-full" />
                                    {(() => {
                                        // Use suggestedQuery if available, otherwise use previousQuery
                                        const comparisonQuery = suggestedQuery || previousQuery
                                        const { count, diffs } = countDifferences(query, comparisonQuery)

                                        let diffString = ''
                                        diffs.forEach((diff) => {
                                            diffString += `${diff.key}: ${diff.val1} -> ${diff.val2}\n`
                                        })

                                        return (
                                            <div className="flex items-center gap-1">
                                                <span>
                                                    {count} {count === 1 ? 'change' : 'changes'}
                                                </span>
                                                {diffString && (
                                                    <Tooltip
                                                        title={<div className="whitespace-pre-line">{diffString}</div>}
                                                    >
                                                        <IconInfo className="text-sm text-muted cursor-help" />
                                                    </Tooltip>
                                                )}
                                            </div>
                                        )
                                    })()}
                                </div>
                                <div className="flex gap-2">
                                    {hasRejected && (
                                        <LemonButton
                                            status="default"
                                            onClick={() => {
                                                onReapplySuggestedInsight()
                                            }}
                                            tooltipPlacement="top"
                                            size="small"
                                            icon={<IconRefresh />}
                                        >
                                            Reapply
                                        </LemonButton>
                                    )}
                                    <LemonButton
                                        status="danger"
                                        onClick={() => {
                                            onRejectSuggestedInsight()
                                        }}
                                        tooltipPlacement="top"
                                        size="small"
                                        icon={<IconX />}
                                    >
                                        Reject changes
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {shouldShowSessionAnalysisWarning ? (
                    <LemonBanner type="info" className="mt-2">
                        When using sessions and session properties, events without session IDs will be excluded from the
                        set of results.{' '}
                        <Link to="https://posthog.com/docs/user-guides/sessions">Learn more about sessions.</Link>
                    </LemonBanner>
                ) : null}
            </>
        </CSSTransition>
    )
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e): e is InsightEditorFilter => !!e)
}
