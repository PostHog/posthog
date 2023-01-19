import {
    AvailableFeature,
    ChartDisplayType,
    FunnelVizType,
    InsightEditorFilter,
    InsightEditorFilterGroup,
    InsightLogicProps,
} from '~/types'
import { CSSTransition } from 'react-transition-group'
import { TrendsSeries, TrendsSeriesLabel } from 'scenes/insights/EditorFilters/TrendsSeries'
import { FEATURE_FLAGS, NON_BREAKDOWN_DISPLAY_TYPES } from 'lib/constants'
import { GlobalAndOrFilters } from 'scenes/insights/EditorFilters/GlobalAndOrFilters'
import { TrendsFormula, TrendsFormulaLabel } from 'scenes/insights/EditorFilters/TrendsFormula'
import { Breakdown } from 'scenes/insights/EditorFilters/Breakdown'
import { LifecycleToggles } from 'scenes/insights/EditorFilters/LifecycleToggles'
import { RetentionSummary } from './RetentionSummary'
import { PathsEventTypes } from './PathsEventTypes'
import { PathsWildcardGroups } from './PathsWildcardGroups'
import { PathsTargetEnd, PathsTargetStart } from './PathsTarget'
import { PathsAdvanced } from './PathsAdvanced'
import { FunnelsQuerySteps } from './FunnelsQuerySteps'
import { FunnelsAdvanced } from './FunnelsAdvanced'
import { PathsExclusions } from './PathsExclusions'
import { EditorFilterGroup } from './EditorFilterGroup'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { insightLogic } from '../insightLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { InsightTypeSelector } from './InsightTypeSelector'
import './EditorFilters.scss'
import clsx from 'clsx'
import { Attribution } from './AttributionFilter'
import {
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

export interface EditorFiltersProps {
    insightProps: InsightLogicProps
    showing: boolean
}

export function EditorFilters({ insightProps, showing }: EditorFiltersProps): JSX.Element {
    const { user } = useValues(userLogic)
    const availableFeatures = user?.organization?.available_features || []

    const logic = insightLogic(insightProps)
    const { filters, insight, filterPropertiesCount } = useValues(logic)

    const { advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const usingEditorPanels = featureFlags[FEATURE_FLAGS.INSIGHT_EDITOR_PANELS]

    const isTrends = isTrendsFilter(filters)
    const isLifecycle = isLifecycleFilter(filters)
    const isStickiness = isStickinessFilter(filters)
    const isRetention = isRetentionFilter(filters)
    const isPaths = isPathsFilter(filters)
    const isFunnels = isFunnelsFilter(filters)
    const isTrendsLike = isTrends || isLifecycle || isStickiness

    const hasBreakdown =
        (isTrends && !NON_BREAKDOWN_DISPLAY_TYPES.includes(filters.display || ChartDisplayType.ActionsLineGraph)) ||
        (isRetention &&
            featureFlags[FEATURE_FLAGS.RETENTION_BREAKDOWN] &&
            (filters as any).display !== ChartDisplayType.ActionsLineGraph) ||
        (isFunnels && filters.funnel_viz_type === FunnelVizType.Steps)
    const hasPropertyFilters = isTrends || isStickiness || isRetention || isPaths || isFunnels || isLifecycle
    const hasPathsAdvanced = availableFeatures.includes(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution = isFunnels && filters.funnel_viz_type === FunnelVizType.Steps

    const advancedOptionsCount = advancedOptionsUsedCount + (isTrends && filters.formula ? 1 : 0)
    const advancedOptionsExpanded = !!advancedOptionsCount

    const editorFilters: InsightEditorFilterGroup[] = [
        {
            title: 'General',
            editorFilters: filterFalsy([
                usingEditorPanels
                    ? {
                          key: 'insight',
                          label: 'Type',
                          component: InsightTypeSelector,
                      }
                    : undefined,
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
                              component: PathsEventTypes,
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
                              //   label: 'Query Steps',
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
            count: filterPropertiesCount,

            editorFilters: filterFalsy([
                isLifecycle
                    ? {
                          key: 'toggles',
                          label: 'Lifecycle Toggles',
                          position: 'right',
                          component: LifecycleToggles,
                      }
                    : null,
                hasPropertyFilters
                    ? {
                          key: 'properties',
                          label: !usingEditorPanels ? 'Filters' : undefined,
                          position: 'right',
                          component: GlobalAndOrFilters,
                      }
                    : null,
            ]),
        },
        {
            title: 'Breakdown',
            count: filters.breakdowns?.length || (filters.breakdown ? 1 : 0),
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
                          component: Attribution,
                      }
                    : null,
            ]),
        },
        {
            title: 'Exclusions',
            position: 'right',
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
            position: 'left',
            defaultExpanded: advancedOptionsExpanded,
            count: advancedOptionsCount,
            editorFilters: filterFalsy([
                isPaths && {
                    key: 'paths-advanced',
                    component: (props) => (
                        <PayGateMini feature={AvailableFeature.PATHS_ADVANCED}>
                            <PathsAdvanced {...props} />
                        </PayGateMini>
                    ),
                },
                isFunnels && {
                    key: 'funnels-advanced',
                    component: FunnelsAdvanced,
                },
            ]),
        },
    ].filter((x) => x.editorFilters.length > 0)

    let legacyEditorFilterGroups: InsightEditorFilterGroup[] = []

    if (!usingEditorPanels) {
        const leftFilters = editorFilters.reduce(
            (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position !== 'right')),
            [] as InsightEditorFilter[]
        )
        const rightFilters = editorFilters.reduce(
            (acc, x) => acc.concat(x.editorFilters.filter((y) => y.position === 'right')),
            [] as InsightEditorFilter[]
        )

        legacyEditorFilterGroups = [
            {
                title: 'Left',
                editorFilters: leftFilters,
            },
            {
                title: 'right',
                editorFilters: rightFilters,
            },
        ]
    }

    return (
        <CSSTransition in={showing} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
            <div
                className={clsx('EditorFiltersWrapper', {
                    'EditorFiltersWrapper--editorpanels': usingEditorPanels,
                    'EditorFiltersWrapper--singlecolumn': usingEditorPanels || isFunnels,
                })}
            >
                <div className="EditorFilters">
                    {(usingEditorPanels || isFunnels ? editorFilters : legacyEditorFilterGroups).map(
                        (editorFilterGroup) => (
                            <EditorFilterGroup
                                key={editorFilterGroup.title}
                                editorFilterGroup={editorFilterGroup}
                                insight={insight}
                                insightProps={insightProps}
                            />
                        )
                    )}
                </div>
            </div>
        </CSSTransition>
    )
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
