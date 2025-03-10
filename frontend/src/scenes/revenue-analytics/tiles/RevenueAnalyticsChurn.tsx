import { LemonCard } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'

import { TileId } from '../revenueAnalyticsLogic'

interface ChurnTileProps {
  tile: {
    tileId: TileId
    title: string
    layout: {
      colSpanClassName?: string
      rowSpanClassName?: string
      orderWhenLargeClassName?: string
      className?: string
    }
  }
}

export const RevenueAnalyticsChurnTile = ({ tile }: ChurnTileProps): JSX.Element => {
  // Sample query for churn visualization
  const query = {
    kind: 'InsightVizNode',
    source: {
      kind: 'TrendsQuery',
      series: [
        {
          kind: 'EventsNode',
          event: 'stripe_subscription_canceled',
          name: 'Subscription Churn',
        },
      ],
      interval: 'month',
      trendsFilter: {
        display: 'ActionsLineGraph',
      },
    },
  }

  return (
    <LemonCard title={tile.title} className="h-full">
      <div className="h-80">
        <Query query={query} readOnly={true} context={{}} />
      </div>
      <div className="grid grid-cols-3 gap-4 mt-4">
        <div className="text-center">
          <div className="text-2xl font-bold">5.2%</div>
          <div className="text-muted">Customer Churn Rate</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold">3.8%</div>
          <div className="text-muted">Revenue Churn Rate</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold">$2,450</div>
          <div className="text-muted">MRR Lost to Churn</div>
        </div>
      </div>
    </LemonCard>
  )
} 