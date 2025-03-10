import { PageHeader } from 'lib/components/PageHeader'
import { RevenueAnalyticsDashboard } from 'scenes/revenue-analytics/RevenueAnalyticsDashboard'
import { revenueAnalyticsLogic } from 'scenes/revenue-analytics/revenueAnalyticsLogic'
import { SceneExport } from 'scenes/sceneTypes'

export function RevenueAnalyticsScene(): JSX.Element {
  return (
    <>
      <PageHeader />
      <RevenueAnalyticsDashboard />
    </>
  )
}

export const scene: SceneExport = {
  component: RevenueAnalyticsScene,
  logic: revenueAnalyticsLogic,
} 