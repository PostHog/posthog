import { router } from 'kea-router'

import {
    IconCheck,
    IconGraph,
    IconPencil,
    IconPlay,
    IconRefresh,
    IconServer,
    IconSparkles,
    IconTrash,
} from '@posthog/icons'

import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { definitionField } from './dataCatalogMetricSceneLogic'
import type { DataCatalogMetricApi } from './generated/api.schemas'

export interface MetricSceneAction {
    key: string
    label: string
    icon: JSX.Element
    onClick: () => void
    disabledReason?: string
    destructive?: boolean
    opensFloatingUi?: boolean
}

export interface MetricSceneActionHandlers {
    approve: () => void
    refreshFromInsight: () => void
    run: () => void
    runWithAI: () => void
    rename: () => void
    delete: () => void
}

export interface MetricSceneActionsInput {
    metric: DataCatalogMetricApi
    mutating: boolean
    biModeEnabled: boolean
    isMaxAvailable: boolean
    handlers: MetricSceneActionHandlers
}

export const DRIFT_APPROVE_DISABLED = 'This metric has drifted from its source insight. Refresh it first.'
export const MAX_UNAVAILABLE_REASON = 'PostHog AI is not available on this instance'
export const NO_RUNNABLE_DEFINITION_REASON = 'This metric has no runnable definition yet'
export const WORKING_REASON = 'Working'
export const RUN_ACTION_KEY = 'run'

export function buildMetricSceneActions({
    metric,
    mutating,
    biModeEnabled,
    isMaxAvailable,
    handlers,
}: MetricSceneActionsInput): MetricSceneAction[] {
    const sourceShortId = metric.source_insight_short_id
    const definitionSql = definitionField(metric, 'query')
    const isApproved = metric.status === 'approved'
    const isMarkdownMetric = metric.definition_kind === 'MarkdownDefinition'

    return [
        ...(biModeEnabled && definitionSql
            ? [
                  {
                      key: 'explore-bi',
                      label: 'Explore in BI',
                      icon: <IconGraph />,
                      onClick: () => router.actions.push(urls.businessIntelligenceNew(), { metric: metric.name }),
                  },
              ]
            : []),
        ...(isApproved
            ? []
            : [
                  {
                      key: 'approve',
                      label: 'Approve',
                      icon: <IconCheck />,
                      onClick: handlers.approve,
                      disabledReason: metric.is_drifted
                          ? DRIFT_APPROVE_DISABLED
                          : mutating
                            ? WORKING_REASON
                            : undefined,
                  },
              ]),
        ...(sourceShortId
            ? [
                  {
                      key: 'refresh',
                      label: 'Refresh from insight',
                      icon: <IconRefresh />,
                      onClick: handlers.refreshFromInsight,
                      disabledReason: mutating ? WORKING_REASON : undefined,
                  },
                  {
                      key: 'source-insight',
                      label: 'View source insight',
                      icon: <IconGraph />,
                      onClick: () => router.actions.push(urls.insightView(sourceShortId as InsightShortId)),
                  },
              ]
            : []),
        isMarkdownMetric
            ? {
                  key: RUN_ACTION_KEY,
                  label: 'Run with AI',
                  icon: <IconSparkles />,
                  onClick: handlers.runWithAI,
                  disabledReason: isMaxAvailable ? undefined : MAX_UNAVAILABLE_REASON,
              }
            : {
                  key: RUN_ACTION_KEY,
                  label: 'Run metric',
                  icon: <IconPlay />,
                  onClick: handlers.run,
                  disabledReason: metric.definition_kind ? undefined : NO_RUNNABLE_DEFINITION_REASON,
              },
        {
            key: 'rename',
            label: 'Rename',
            icon: <IconPencil />,
            onClick: handlers.rename,
            disabledReason: mutating ? WORKING_REASON : undefined,
            opensFloatingUi: true,
        },
        ...(definitionSql
            ? [
                  {
                      key: 'open-sql',
                      label: 'Open in SQL editor',
                      icon: <IconServer />,
                      onClick: () => router.actions.push(urls.sqlEditor({ source: 'metric', metricName: metric.name })),
                  },
              ]
            : []),
        {
            key: 'delete',
            label: 'Delete',
            icon: <IconTrash />,
            onClick: handlers.delete,
            destructive: true,
            opensFloatingUi: true,
        },
    ]
}
