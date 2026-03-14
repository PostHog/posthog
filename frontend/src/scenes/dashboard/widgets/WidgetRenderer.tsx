import { Suspense, lazy } from 'react'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { DashboardWidgetModel, DashboardWidgetType } from '~/types'

const ExperimentWidget = lazy(() => import('./ExperimentWidget'))
const LogsWidget = lazy(() => import('./LogsWidget'))
const ErrorTrackingWidget = lazy(() => import('./ErrorTrackingWidget'))
const SessionReplaysWidget = lazy(() => import('./SessionReplaysWidget'))
const SurveyResponsesWidget = lazy(() => import('./SurveyResponsesWidget'))

interface WidgetRendererProps {
    tileId: number
    widget: DashboardWidgetModel
}

function WidgetFallback(): JSX.Element {
    return (
        <div className="p-4 space-y-2">
            <LemonSkeleton className="h-4 w-3/4" />
            <LemonSkeleton className="h-4 w-1/2" />
            <LemonSkeleton className="h-32 w-full" />
        </div>
    )
}

export function WidgetRenderer({ tileId, widget }: WidgetRendererProps): JSX.Element {
    const { widget_type, config } = widget

    return (
        <Suspense fallback={<WidgetFallback />}>
            {widget_type === DashboardWidgetType.Experiment && (
                <ExperimentWidget tileId={tileId} config={config} />
            )}
            {widget_type === DashboardWidgetType.Logs && <LogsWidget tileId={tileId} config={config} />}
            {widget_type === DashboardWidgetType.ErrorTracking && (
                <ErrorTrackingWidget tileId={tileId} config={config} />
            )}
            {widget_type === DashboardWidgetType.SessionReplays && (
                <SessionReplaysWidget tileId={tileId} config={config} />
            )}
            {widget_type === DashboardWidgetType.SurveyResponses && (
                <SurveyResponsesWidget tileId={tileId} config={config} />
            )}
        </Suspense>
    )
}
