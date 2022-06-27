import {
    AvailableFeature,
    ChartDisplayType,
    FunnelVizType,
    InsightEditorFilter,
    InsightEditorFilterGroup,
    InsightLogicProps,
    InsightType,
} from '~/types'
import { CSSTransition } from 'react-transition-group'
import { EFTrendsSteps } from 'scenes/insights/EditorFilters/EFTrendsSteps'
import { FEATURE_FLAGS } from 'lib/constants'
import { EFTrendsGlobalAndOrFilters } from 'scenes/insights/EditorFilters/EFTrendsGlobalAndOrFilters'
import { EFTrendsFormula } from 'scenes/insights/EditorFilters/EFTrendsFormula'
import { EFTrendsBreakdown } from 'scenes/insights/EditorFilters/EFTrendsBreakdown'
import { EFLifecycleToggles } from 'scenes/insights/EditorFilters/EFLifecycleToggles'
import { EFLifecycleGlobalFilters } from 'scenes/insights/EditorFilters/EFLifecycleGlobalFilters'
import React from 'react'
import { EFRetentionSummary } from './EFRetentionSummary'
import { EFPathsEventTypes } from './EFPathsEventTypes'
import { EFPathsWildcardGroups } from './EFPathsWildcardGroups'
import { EFPathsTargetEnd, EFPathsTargetStart } from './EFPathsTarget'
import { EFPathsAdvanced } from './EFPathsAdvanced'
import { EFFunnelsQuerySteps } from './EFFunnelsQuerySteps'
import { EFFunnelsAdvanced } from './EFFunnelsAdvanced'
import { EFPathsExclusions } from './EFPathsExclusions'
import { EditorFilterGroup } from './EditorFilterGroup'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { insightLogic } from '../insightLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { EFPathsAdvancedPaywall } from './EFPathsAdvancedPaywall'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { EFInsightType } from './EFInsightType'
import './EditorFilters.scss'
import clsx from 'clsx'
import { EFAttribution } from './EFAttribution'

export interface EditorFiltersProps {
    insightProps: InsightLogicProps
    showing: boolean
}

export function EditorFilters({ insightProps, showing }: EditorFiltersProps): JSX.Element {
    const { user } = useValues(userLogic)
    const availableFeatures = user?.organization?.available_features || []

    const logic = insightLogic(insightProps)
    const { filters, insight, filterPropertiesCount } = useValues(logic)
    const { preflight } = useValues(preflightLogic)

    const { advancedOptionsUsedCount } = useValues(funnelLogic(insightProps))

    const { featureFlags } = useValues(featureFlagLogic)
    const usingEditorPanels = featureFlags[FEATURE_FLAGS.INSIGHT_EDITOR_PANELS]

    const isTrends = !filters.insight || filters.insight === InsightType.TRENDS
    const isLifecycle = filters.insight === InsightType.LIFECYCLE
    const isStickiness = filters.insight === InsightType.STICKINESS
    const isRetention = filters.insight === InsightType.RETENTION
    const isPaths = filters.insight === InsightType.PATHS
    const isFunnels = filters.insight === InsightType.FUNNELS
    const isTrendsLike = isTrends || isLifecycle || isStickiness

    const hasBreakdown =
        isTrends ||
        (isRetention &&
            featureFlags[FEATURE_FLAGS.RETENTION_BREAKDOWN] &&
            filters.display !== ChartDisplayType.ActionsLineGraph) ||
        (isFunnels && filters.funnel_viz_type === FunnelVizType.Steps)
    const hasPropertyFilters = isTrends || isStickiness || isRetention || isPaths || isFunnels
    const hasPathsAdvanced = availableFeatures.includes(AvailableFeature.PATHS_ADVANCED)
    const hasAttribution =
        isFunnels &&
        filters.funnel_viz_type === FunnelVizType.Steps &&
        featureFlags[FEATURE_FLAGS.BREAKDOWN_ATTRIBUTION]

    const advancedOptionsCount = advancedOptionsUsedCount + (filters.formula ? 1 : 0)
    const advancedOptionsExpanded = !!advancedOptionsCount

    const editorFilters: InsightEditorFilterGroup[] = [
        {
            title: 'General',
            editorFilters: filterFalsy([
                usingEditorPanels
                    ? {
                          key: 'insight',
                          label: 'Type',
                          component: EFInsightType,
                      }
                    : undefined,
                isRetention && {
                    key: 'retention-summary',
                    label: 'Retention Summary',
                    component: EFRetentionSummary,
                },
                ...(isPaths
                    ? filterFalsy([
                          {
                              key: 'event-types',
                              label: 'Event Types',
                              component: EFPathsEventTypes,
                          },
                          hasPathsAdvanced && {
                              key: 'wildcard-groups',
                              label: 'Wildcard Groups (optional)',
                              component: EFPathsWildcardGroups,
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
                              component: EFPathsTargetStart,
                          },
                          hasPathsAdvanced && {
                              key: 'ends-target',
                              label: 'Ends at',
                              component: EFPathsTargetEnd,
                          },
                      ])
                    : []),
                ...(isFunnels
                    ? filterFalsy([
                          {
                              key: 'query-steps',
                              //   label: 'Query Steps',
                              component: EFFunnelsQuerySteps,
                          },
                      ])
                    : []),
            ]),
        },
        {
            title: 'Steps',

            editorFilters: filterFalsy([
                isTrendsLike && {
                    key: 'steps',
                    component: EFTrendsSteps,
                },
            ]),
        },
        {
            title: 'Filters',
            count: filterPropertiesCount,

            editorFilters: filterFalsy([
                isLifecycle
                    ? {
                          key: 'properties',
                          label: !usingEditorPanels ? 'Filters' : undefined,
                          position: 'right',
                          component: EFLifecycleGlobalFilters,
                      }
                    : null,
                isLifecycle
                    ? {
                          key: 'toggles',
                          label: 'Lifecycle Toggles',
                          position: 'right',
                          component: EFLifecycleToggles,
                      }
                    : null,
                hasPropertyFilters && filters.properties
                    ? {
                          key: 'properties',
                          label: !usingEditorPanels ? 'Filters' : undefined,
                          position: 'right',
                          component: EFTrendsGlobalAndOrFilters,
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
                          component: EFTrendsBreakdown,
                      }
                    : null,
                hasAttribution
                    ? {
                          key: 'attribution',
                          label: 'Attribution type',
                          position: 'right',

                          tooltip: <>filler</>,
                          component: EFAttribution,
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
                    component: EFPathsExclusions,
                },
            ]),
        },
        {
            title: 'Advanced Options',
            position: 'left',
            defaultExpanded: advancedOptionsExpanded,
            count: advancedOptionsCount,
            editorFilters: filterFalsy([
                isTrends
                    ? {
                          key: 'formula',
                          label: 'Formula',
                          position: 'right',
                          tooltip: (
                              <>
                                  Apply math operations to your series. You can do operations among series (e.g.{' '}
                                  <code>A / B</code>) or simple arithmetic operations on a single series (e.g.{' '}
                                  <code>A / 100</code>)
                              </>
                          ),
                          component: EFTrendsFormula,
                      }
                    : null,
                isPaths &&
                    (hasPathsAdvanced
                        ? {
                              key: 'paths-advanced',
                              component: EFPathsAdvanced,
                          }
                        : !preflight?.instance_preferences?.disable_paid_fs
                        ? {
                              key: 'paths-paywall',
                              component: EFPathsAdvancedPaywall,
                          }
                        : undefined),
                isFunnels && {
                    key: 'funnels-advanced',
                    component: EFFunnelsAdvanced,
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
                })}
            >
                <div className="EditorFilters">
                    {(usingEditorPanels ? editorFilters : legacyEditorFilterGroups).map((editorFilterGroup) => (
                        <EditorFilterGroup
                            key={editorFilterGroup.title}
                            editorFilterGroup={editorFilterGroup}
                            insight={insight}
                            insightProps={insightProps}
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
