import { FilterType, InsightEditorFilter, InsightEditorFilterGroups, InsightType } from '~/types'
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

export function getEditorFilters(
    filters: Partial<FilterType>,
    featureFlags: FeatureFlagsSet
): InsightEditorFilterGroups {
    const isTrends = !filters.insight || filters.insight === InsightType.TRENDS
    const isLifecycle = filters.insight === InsightType.LIFECYCLE
    const isStickiness = filters.insight === InsightType.STICKINESS
    const isRetention = filters.insight === InsightType.RETENTION
    const isTrendsLike = isTrends || isLifecycle || isStickiness

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
            (isTrends || isStickiness || isRetention) && filters.properties
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
            isTrends
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
        ]),
    }
}

function filterFalsy(a: (InsightEditorFilter | false | null | undefined)[]): InsightEditorFilter[] {
    return a.filter((e) => !!e) as InsightEditorFilter[]
}
