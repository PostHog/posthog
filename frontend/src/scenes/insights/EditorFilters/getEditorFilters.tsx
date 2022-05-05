import {
    AvailableFeature,
    FilterType,
    FunnelVizType,
    InsightEditorFilter,
    InsightEditorFilterGroups,
    InsightType,
} from '~/types'
import { EFInsightType } from 'scenes/insights/EditorFilters/EFInsightType'
import { EFTrendsSteps } from 'scenes/insights/EditorFilters/EFTrendsSteps'
import { EFTrendsGlobalFilters } from 'scenes/insights/EditorFilters/EFTrendsGlobalFilters'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
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
import { EFPathsAdvanced, EFPathsAdvancedPaywall } from './EFPathsAdvanced'
import { EFFunnelsQuerySteps } from './EFFunnelsQuerySteps'
import { EFFunnelsAdvanced } from './EFFunnelsAdvanced'

export function getEditorFilters(
    filters: Partial<FilterType>,
    featureFlags: FeatureFlagsSet,
    availableFeatures: AvailableFeature[]
): InsightEditorFilterGroups {
    const isTrends = !filters.insight || filters.insight === InsightType.TRENDS
    const isLifecycle = filters.insight === InsightType.LIFECYCLE
    const isStickiness = filters.insight === InsightType.STICKINESS
    const isRetention = filters.insight === InsightType.RETENTION
    const isPaths = filters.insight === InsightType.PATHS
    const isFunnels = filters.insight === InsightType.FUNNELS
    const isTrendsLike = isTrends || isLifecycle || isStickiness

    const hasBreakdown = isTrends || (isFunnels && filters.funnel_viz_type === FunnelVizType.Steps)
    const hasPropertyFilters = isTrends || isStickiness || isRetention || isPaths || isFunnels
    const hasPathsAdvanced = availableFeatures.includes(AvailableFeature.PATHS_ADVANCED) || true

    return {
        General: filterFalsy([
            {
                key: 'insight',
                label: 'Type',
                component: EFInsightType,
            },
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
                                  /merchant/1234/payment, replace the unique value with an asterisk /merchant/*/payment.{' '}
                                  <b>Use a comma to separate multiple wildcards.</b>
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
        Steps: filterFalsy([
            isTrendsLike && {
                key: 'steps',
                component: EFTrendsSteps,
            },
        ]),
        Filters: filterFalsy([
            isLifecycle
                ? {
                      key: 'properties',
                      label: 'Filters',
                      component: EFLifecycleGlobalFilters,
                      tooltip: (
                          <>
                              These filters will apply to <b>all</b> the actions/events in this graph.
                          </>
                      ),
                  }
                : null,
            isLifecycle
                ? {
                      key: 'toggles',
                      label: 'Lifecycle Toggles',
                      component: EFLifecycleToggles,
                  }
                : null,
            hasPropertyFilters && filters.properties
                ? {
                      key: 'properties',
                      component: featureFlags[FEATURE_FLAGS.AND_OR_FILTERING]
                          ? EFTrendsGlobalAndOrFilters
                          : EFTrendsGlobalFilters,
                  }
                : null,
        ]),
        Custom: filterFalsy([
            isTrends
                ? {
                      key: 'formula',
                      label: 'Formula',
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
            hasBreakdown
                ? {
                      key: 'breakdown',
                      label: 'Breakdown by',
                      tooltip: (
                          <>
                              Use breakdown to see the aggregation (total volume, active users, etc.) for each value of
                              that property. For example, breaking down by Current URL with total volume will give you
                              the event volume for each URL your users have visited.
                          </>
                      ),
                      component: EFTrendsBreakdown,
                  }
                : null,
            isPaths &&
                (hasPathsAdvanced
                    ? {
                          key: 'paths-advanced',
                          //   label: 'Advanced Options',
                          component: EFPathsAdvanced,
                      }
                    : {
                          key: 'paths-paywall',
                          label: 'Paywall',
                          component: EFPathsAdvancedPaywall,
                      }),
            isFunnels && {
                key: 'funnels-advanced',
                //   label: 'Advanced Options',
                component: EFFunnelsAdvanced,
            },
        ]),
    }
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
