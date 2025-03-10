import { LemonTable } from '@posthog/lemon-ui'

import { TileId } from '../revenueAnalyticsLogic'

interface CustomersTileProps {
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

export const RevenueAnalyticsCustomersTile = ({ tile }: CustomersTileProps): JSX.Element => {
  // Sample data - in a real implementation, this would come from your API
  const customers = [
    { id: 1, name: 'Acme Corp', email: 'billing@acme.com', mrr: 499, plan: 'Business', status: 'Active', since: '2023-01-15' },
    { id: 2, name: 'Globex', email: 'finance@globex.com', mrr: 999, plan: 'Enterprise', status: 'Active', since: '2022-11-03' },
    { id: 3, name: 'Initech', email: 'accounts@initech.com', mrr: 199, plan: 'Starter', status: 'Active', since: '2023-03-22' },
    { id: 4, name: 'Umbrella Corp', email: 'billing@umbrella.com', mrr: 499, plan: 'Business', status: 'Past due', since: '2022-08-17' },
    { id: 5, name: 'Stark Industries', email: 'finance@stark.com', mrr: 1999, plan: 'Enterprise+', status: 'Active', since: '2022-05-04' },
  ]

  return (
    <div className="border rounded p-4">
      <h3 className="mb-4">{tile.title}</h3>
      <LemonTable
        dataSource={customers}
        columns={[
          {
            title: 'Customer',
            dataIndex: 'name',
            render: (name, record) => (
              <div>
                <div>{name}</div>
                <div className="text-muted">{record.email}</div>
              </div>
            ),
          },
          {
            title: 'MRR',
            dataIndex: 'mrr',
            render: (mrr) => `$${mrr}`,
          },
          {
            title: 'Plan',
            dataIndex: 'plan',
          },
          {
            title: 'Status',
            dataIndex: 'status',
            render: (status) => (
              <div className={status === 'Active' ? 'text-success' : 'text-danger'}>
                {status}
              </div>
            ),
          },
          {
            title: 'Customer since',
            dataIndex: 'since',
          },
        ]}
      />
    </div>
  )
} 