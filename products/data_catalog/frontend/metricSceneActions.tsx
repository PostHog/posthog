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

export type MetricSceneMenu = 'file' | 'edit' | 'view'

export interface MetricSceneAction {
    key: string
    menu: MetricSceneMenu
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
    running: boolean
    isMaxAvailable: boolean
    handlers: MetricSceneActionHandlers
}

export const DRIFT_APPROVE_DISABLED = 'This metric has drifted from its source insight. Refresh it first.'
export const MAX_UNAVAILABLE_REASON = 'PostHog AI is not available on this instance'
export const NO_RUNNABLE_DEFINITION_REASON = 'This metric has no runnable definition yet'
export const WORKING_REASON = 'Working'
export const RUNNING_REASON = 'The metric is running'
export const RUN_ACTION_KEY = 'run'

export function buildMetricSceneActions({
    metric,
    mutating,
    running,
    isMaxAvailable,
    handlers,
}: MetricSceneActionsInput): MetricSceneAction[] {
    const sourceShortId = metric.source_insight_short_id
    const definitionSql = definitionField(metric, 'query')
    const isApproved = metric.status === 'approved'
    const isMarkdownMetric = metric.definition_kind === 'MarkdownDefinition'

    return [
        ...(definitionSql
            ? [
                  {
                      key: 'explore-bi',
                      menu: 'file' as const,
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
                      menu: 'edit' as const,
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
                      menu: 'edit' as const,
                      label: 'Refresh from insight',
                      icon: <IconRefresh />,
                      onClick: handlers.refreshFromInsight,
                      disabledReason: mutating ? WORKING_REASON : undefined,
                  },
                  {
                      key: 'source-insight',
                      menu: 'view' as const,
                      label: 'View source insight',
                      icon: <IconGraph />,
                      onClick: () => router.actions.push(urls.insightView(sourceShortId as InsightShortId)),
                  },
              ]
            : []),
        isMarkdownMetric
            ? {
                  key: RUN_ACTION_KEY,
                  menu: 'file',
                  label: 'Run with AI',
                  icon: <IconSparkles />,
                  onClick: handlers.runWithAI,
                  disabledReason: isMaxAvailable ? undefined : MAX_UNAVAILABLE_REASON,
                  opensFloatingUi: true,
              }
            : {
                  key: RUN_ACTION_KEY,
                  menu: 'file',
                  label: 'Run metric',
                  icon: <IconPlay />,
                  onClick: handlers.run,
                  disabledReason: !metric.definition_kind
                      ? NO_RUNNABLE_DEFINITION_REASON
                      : running
                        ? RUNNING_REASON
                        : undefined,
              },
        {
            key: 'rename',
            menu: 'edit',
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
                      menu: 'file' as const,
                      label: 'Open in SQL editor',
                      icon: <IconServer />,
                      onClick: () => router.actions.push(urls.sqlEditor({ source: 'metric', metricName: metric.name })),
                  },
              ]
            : []),
        {
            key: 'delete',
            menu: 'file',
            label: 'Delete',
            icon: <IconTrash />,
            onClick: handlers.delete,
            destructive: true,
        },
    ]
}
