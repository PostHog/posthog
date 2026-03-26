import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

import { IconInfo, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, Link, Tooltip } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { pluralize } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { Attribution } from 'scenes/insights/EditorFilters/AttributionFilter'
import { FunnelsAdvanced } from 'scenes/insights/EditorFilters/FunnelsAdvanced'
import { FunnelsQuerySteps } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { FunnelStepConfiguration } from 'scenes/insights/EditorFilters/FunnelStepConfiguration'
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
import { SamplingDeprecationNotice } from 'scenes/insights/EditorFilters/SamplingDeprecationNotice'
import { WebAnalyticsEditorFilters } from 'scenes/insights/EditorFilters/WebAnalyticsEditorFilters'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { compareInsightTopLevelSections } from 'scenes/insights/utils'
import MaxTool from 'scenes/max/MaxTool'
import { castAssistantQuery } from 'scenes/max/utils'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { userLogic } from 'scenes/userLogic'

import { StickinessCriteria } from '~/queries/nodes/InsightViz/StickinessCriteria'
import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from '~/queries/schema/schema-assistant-queries'
import {
    BreakdownFilter,
    DataVisualizationNode,
    InsightQueryNode,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    WebOverviewQuery,
    WebStatsTableQuery,
} from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode, isWebAnalyticsInsightQuery } from '~/queries/utils'
import {
    AnyPropertyFilter,
    AvailableFeature,
    ChartDisplayType,
    EditorFilterProps,
    InsightEditorFilter,
    InsightEditorFilterGroup,
    PathType,
    PropertyGroupFilter,
} from '~/types'

import { Breakdown } from './Breakdown'
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
    const editorPanelsEnabled = useFeatureFlag('PRODUCT_ANALYTICS_SIMPLE_EDITOR')

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
        pathsFilter,
        querySource,
        shouldShowSessionAnalysisWarning,
        hasFormula,
        series,
        breakdownFilter,
        properties,
    } = useValues(insightVizDataLogic(insightProps))

    const { handleInsightSuggested, onRejectSuggestedInsight } = useActions(insightLogic(insightProps))
    const { previousQuery, suggestedQuery } = useValues(insightLogic(insightProps))
    const { isStepsFunnel, isTrendsFunnel } = useValues(funnelDataLogic(insightProps))
    const { setQuery } = useActions(insightVizDataLogic(insightProps))

    const maxSuggestionActionsBanner = useRef<HTMLDivElement>(null)
    const panelRef = useRef<HTMLDivElement>(null)
    const resizerProps = useMemo(
        () => ({
            logicKey: 'insight-editor-panel',
            persistent: true,
            placement: 'right' as const,
            containerRef: panelRef,
        }),
        []
    )
    const { desiredSize: panelWidth, isResizeInProgress: isResizing } = useValues(resizerLogic(resizerProps))

    useEffect(() => {
        if (previousQuery && maxSuggestionActionsBanner.current) {
            maxSuggestionActionsBanner.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [previousQuery])

    if (!querySource) {
        return null
    }

    // Web Analytics insights use their custom filter UI
    if (isWebAnalyticsInsightQuery(query)) {
        return (
            <WebAnalyticsEditorFilters
                query={query as WebOverviewQuery | WebStatsTableQuery}
                showing={showing}
                embedded={embedded}
            />
        )
    }

    // MaxTool should not be active when insights are embedded (e.g., in notebooks)
    const maxToolActive = !embedded

    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(display || ChartDisplayType.ActionsLineGraph)) ||
        isStepsFunnel ||
        isTrendsFunnel ||
        isRetention
    const hasPathsAdvanced = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution = isStepsFunnel || isTrendsFunnel
    const hasPathsHogQL = isPaths && pathsFilter?.includeEventTypes?.includes(PathType.HogQL)
    const displayGoalLines =
        (isTrends &&
            [ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsLineGraphCumulative].includes(
                display || ChartDisplayType.ActionsLineGraph
            )) ||
        (isFunnels && isTrendsFunnel) ||
        (isRetention &&
            [ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsBar].includes(
                display || ChartDisplayType.ActionsLineGraph
            ))

    // Compute summaries for collapsible sections (used when editorPanelsEnabled)
    const seriesSummary = editorPanelsEnabled ? getSeriesSummary(series) : null
    const filtersSummary = editorPanelsEnabled ? getFiltersSummary(properties) : null
    const breakdownSummary = editorPanelsEnabled ? getBreakdownSummary(breakdownFilter) : null
    const exclusionCount = editorPanelsEnabled && isPaths ? (pathsFilter?.excludeEvents?.length ?? 0) : 0
    const exclusionsSummary = exclusionCount > 0 ? pluralize(exclusionCount, 'exclusion') : null

    const leftEditorFilterGroups: InsightEditorFilterGroup[] = [
        ...(editorPanelsEnabled && isRetention
            ? [
                  {
                      title: 'Retention condition',
                      defaultExpanded: true,
                      editorFilters: [
                          {
                              key: 'retention-condition',
                              component: RetentionCondition,
                          },
                      ],
                  },
                  {
                      title: 'Calculation options',
                      defaultExpanded: false,
                      editorFilters: [
                          {
                              key: 'retention-options',
                              component: RetentionOptions,
                          },
                      ],
                  },
              ]
            : [
                  {
                      title: 'General',
                      ...(editorPanelsEnabled ? { defaultExpanded: true } : {}),
                      editorFilters: filterFalsy([
                          ...(!editorPanelsEnabled && isRetention
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
                                                Use wildcard matching to group events by unique values in path item
                                                names. Use an asterisk (*) in place of unique values. For example,
                                                instead of /merchant/1234/payment, replace the unique value with an
                                                asterisk /merchant/*/payment.{' '}
                                                <b>Use a comma to separate multiple wildcards.</b>
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
              ]),
        {
            title: 'Series',
            ...(editorPanelsEnabled ? { defaultExpanded: true, collapsedSummary: seriesSummary } : {}),
            editorFilters: filterFalsy([
                isTrendsLike && {
                    key: 'series',
                    label:
                        !editorPanelsEnabled &&
                        isTrends &&
                        display !== ChartDisplayType.CalendarHeatmap &&
                        display !== ChartDisplayType.BoxPlot
                            ? TrendsSeriesLabel
                            : undefined,
                    component: TrendsSeries,
                },
                !editorPanelsEnabled && isTrends && hasFormula && display !== ChartDisplayType.BoxPlot
                    ? {
                          key: 'formula',
                          label: 'Formula',
                          component: TrendsFormula,
                      }
                    : null,
            ]),
        },
        {
            title: editorPanelsEnabled
                ? isFunnels
                    ? 'Funnel settings'
                    : isPaths
                      ? 'Path settings'
                      : 'Advanced options'
                : 'Advanced options',
            ...(editorPanelsEnabled ? { defaultExpanded: false } : {}),
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-advanced',
                    component: PathsAdvanced,
                },
                isFunnels &&
                    editorPanelsEnabled && {
                        key: 'funnel-step-configuration',
                        component: FunnelStepConfiguration,
                    },
                isFunnels && {
                    key: 'funnels-advanced',
                    component: FunnelsAdvanced,
                },
            ]),
        },
    ].filter((g): g is InsightEditorFilterGroup => !!g)

    const rightEditorFilterGroups: InsightEditorFilterGroup[] = [
        {
            title: 'Filters',
            ...(editorPanelsEnabled ? { defaultExpanded: false, collapsedSummary: filtersSummary } : {}),
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
                    label: editorPanelsEnabled ? undefined : 'Filters',
                    component: GlobalAndOrFilters as (props: EditorFilterProps) => JSX.Element | null,
                },
            ]),
        },
        {
            title: 'Breakdown',
            ...(editorPanelsEnabled ? { defaultExpanded: false, collapsedSummary: breakdownSummary } : {}),
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
                                  <span>Breakdown attribution</span>
                                  <Tooltip
                                      closeDelayMs={200}
                                      interactive
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
            ...(editorPanelsEnabled ? { defaultExpanded: false, collapsedSummary: exclusionsSummary } : {}),
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
        // Hide advanced options for calendar heatmap
        display !== ChartDisplayType.CalendarHeatmap
            ? {
                  title: 'Advanced options',
                  defaultExpanded: false,
                  editorFilters: filterFalsy([
                      {
                          key: 'poe',
                          component: PoeFilter,
                      },
                      displayGoalLines && {
                          key: 'goal-lines',
                          label: 'Goal lines',
                          tooltip: (
                              <>
                                  Goal lines can be used to highlight specific goals (Revenue, Signups, etc.) or limits
                                  (Web Vitals, etc.)
                              </>
                          ),
                          component: GoalLines,
                      },
                      {
                          key: 'sampling-deprecation',
                          component: SamplingDeprecationNotice,
                      },
                  ]),
              }
            : null,
    ].filter((group): group is InsightEditorFilterGroup => group !== null)

    const filterGroupsGroups = editorPanelsEnabled
        ? [
              {
                  title: 'single',
                  editorFilterGroups: [
                      ...leftEditorFilterGroups.filter((group) => group.editorFilters.length > 0),
                      ...rightEditorFilterGroups.filter((group) => group.editorFilters.length > 0),
                  ],
              },
          ]
        : [
              {
                  title: 'left',
                  editorFilterGroups: leftEditorFilterGroups.filter((group) => group.editorFilters.length > 0),
              },
              {
                  title: 'right',
                  editorFilterGroups: rightEditorFilterGroups.filter((group) => group.editorFilters.length > 0),
              },
          ]

    const QueryTypeIcon = QUERY_TYPES_METADATA[query.kind].icon

    const maxToolProps = {
        identifier: 'create_insight' as const,
        context: { current_query: querySource },
        contextDescription: { text: 'Current query', icon: <QueryTypeIcon /> },
        callback: (
            toolOutput: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
        ) => {
            const source = castAssistantQuery(toolOutput)
            if (!source) {
                return
            }
            let node: QuerySchema
            if (isHogQLQuery(source)) {
                node = { kind: NodeKind.DataVisualizationNode, source } satisfies DataVisualizationNode
            } else if (isInsightQueryNode(source)) {
                node = { kind: NodeKind.InsightVizNode, source } satisfies InsightVizNode
            } else {
                node = source
            }
            handleInsightSuggested(node)
            setQuery(node)
        },
        initialMaxPrompt: 'Show me users who ',
        active: maxToolActive,
    }

    const filterContent = (
        <div
            className={clsx(
                '@container/editor',
                editorPanelsEnabled ? 'flex flex-col gap-3' : 'flex flex-row flex-wrap gap-8 bg-surface-primary',
                { 'p-4 rounded border': !embedded && !editorPanelsEnabled }
            )}
        >
            {filterGroupsGroups.map(({ title, editorFilterGroups }) => (
                <div
                    key={title}
                    className={clsx(
                        'flex flex-col max-w-full',
                        editorPanelsEnabled ? 'gap-3' : 'gap-4 grow shrink basis-[28rem]'
                    )}
                >
                    {editorFilterGroups.map((editorFilterGroup) => (
                        <EditorFilterGroup
                            key={editorFilterGroup.title}
                            editorFilterGroup={editorFilterGroup}
                            insightProps={insightProps}
                            query={query}
                            asTile={editorPanelsEnabled}
                        />
                    ))}
                </div>
            ))}
        </div>
    )

    const suggestionBanner = previousQuery ? (
        <div className="w-full px-2" ref={maxSuggestionActionsBanner}>
            <div className="bg-surface-tertiary/80 w-full flex justify-between items-center p-1 pl-2 mx-auto rounded-bl rounded-br">
                <div className="text-sm text-muted flex items-center gap-2 no-wrap">
                    <span className="size-2 bg-accent-active rounded-full" />
                    {(() => {
                        const changedLabels = compareInsightTopLevelSections(previousQuery, suggestedQuery)
                        const diffString = `🔍 ${pluralize(
                            changedLabels.length,
                            'section'
                        )} changed: \n${changedLabels.join('\n')}`
                        return (
                            <div className="flex items-center gap-1">
                                <span>{pluralize(changedLabels.length, 'change')}</span>
                                {diffString && (
                                    <Tooltip title={<div className="whitespace-pre-line">{diffString}</div>}>
                                        <IconInfo className="text-sm text-muted cursor-help" />
                                    </Tooltip>
                                )}
                            </div>
                        )
                    })()}
                </div>
                <LemonButton
                    status="danger"
                    onClick={() => onRejectSuggestedInsight()}
                    tooltipPlacement="top"
                    size="small"
                    icon={<IconX />}
                >
                    Reject changes
                </LemonButton>
            </div>
        </div>
    ) : null

    const sessionWarning = shouldShowSessionAnalysisWarning ? (
        <LemonBanner type="info" className="mb-4">
            When using sessions and session properties, events without session IDs will be excluded from the set of
            results. <Link to="https://posthog.com/docs/user-guides/sessions">Learn more about sessions.</Link>
        </LemonBanner>
    ) : null

    if (!editorPanelsEnabled) {
        return (
            <CSSTransition in={showing} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
                <div className="EditorFiltersWrapper">
                    {sessionWarning}
                    <div>
                        <MaxTool {...maxToolProps}>{filterContent}</MaxTool>
                        {suggestionBanner}
                    </div>
                </div>
            </CSSTransition>
        )
    }

    return (
        <div
            ref={panelRef}
            className={clsx(
                'EditorFiltersWrapper relative self-stretch @container/editor-panel',
                isResizing ? '' : 'transition-all duration-300 ease-out',
                showing ? 'opacity-100' : 'w-0 min-w-0 max-w-0 opacity-0 overflow-hidden border-0 !p-0'
            )}
            style={
                showing && panelWidth
                    ? { width: panelWidth, minWidth: 320, maxWidth: 600 }
                    : showing
                      ? { width: 'max(min(30%, 600px), 420px)', minWidth: 320, maxWidth: 600 }
                      : undefined
            }
        >
            {showing && <Resizer {...resizerProps} />}
            <MaxTool {...maxToolProps} className="h-full [&_button.absolute]:!-top-1 [&_button.absolute]:!-right-1">
                <div className={clsx('h-full overflow-y-auto', showing && 'px-3 pt-2 pb-4')}>
                    {sessionWarning}
                    {filterContent}
                    {suggestionBanner}
                </div>
            </MaxTool>
        </div>
    )
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e): e is InsightEditorFilter => !!e)
}

export function getFiltersSummary(
    properties: AnyPropertyFilter[] | PropertyGroupFilter | undefined | null
): string | null {
    if (!properties) {
        return null
    }
    const filters: AnyPropertyFilter[] = Array.isArray(properties)
        ? properties
        : properties.values.flatMap((group) => group.values.filter((v): v is AnyPropertyFilter => 'key' in v))
    if (filters.length === 0) {
        return null
    }
    const names = filters.map((f) => ('key' in f && f.key ? String(f.key) : null)).filter(Boolean)
    return names.length > 0 ? names.join(', ') : pluralize(filters.length, 'filter')
}

export function getBreakdownSummary(breakdownFilter: BreakdownFilter | null | undefined): string | null {
    if (!breakdownFilter) {
        return null
    }
    const breakdowns = breakdownFilter.breakdowns
    if (breakdowns?.length) {
        const names = breakdowns.map((b) => b.property).filter(Boolean)
        return names.length > 0 ? names.join(', ') : null
    }
    if (breakdownFilter.breakdown) {
        const bd = breakdownFilter.breakdown
        if (typeof bd === 'string') {
            return bd
        }
        // Numeric values (e.g. cohort IDs) aren't meaningful to display
        const count = Array.isArray(bd) ? bd.length : 1
        return pluralize(count, 'breakdown')
    }
    return null
}

export function getSeriesSummary(
    series: { custom_name?: string; name?: string; event?: string | null }[] | null | undefined
): string | null {
    if (!series || series.length === 0) {
        return null
    }
    const names = series.map((s) => s.custom_name || ('event' in s && s.event) || s.name).filter(Boolean)
    return names.length > 0 ? names.join(', ') : pluralize(series.length, 'series')
}
