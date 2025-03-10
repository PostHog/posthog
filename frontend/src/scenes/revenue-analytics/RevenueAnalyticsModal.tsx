import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'

import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'
import { RevenueQuery } from './tiles/RevenueAnalyticsTile'

export const RevenueAnalyticsModal = (): JSX.Element => {
  const { modalTileId, modalTabId, dateRange } = useValues(revenueAnalyticsLogic)
  const { closeModal, setModalTab } = useActions(revenueAnalyticsLogic)
  const [localDateRange, setLocalDateRange] = useState(dateRange)

  if (!modalTileId) {
    return <></>
  }

  const getTileData = () => {
    // This would fetch the appropriate tile data based on modalTileId and modalTabId
    return {
      title: 'Revenue Details',
      tabs: [
        { id: 'overview', label: 'Overview' },
        { id: 'details', label: 'Details' },
      ],
      query: {
        kind: 'InsightVizNode',
        source: {
          kind: 'TrendsQuery',
          series: [],
        },
      },
    }
  }

  const tileData = getTileData()

  return (
    <LemonModal
      isOpen={!!modalTileId}
      onClose={closeModal}
      width="90%"
      title={tileData.title}
      footer={
        <div className="flex justify-end">
          <LemonButton type="secondary" onClick={closeModal}>
            Close
          </LemonButton>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <LemonTabs
            activeKey={modalTabId || 'overview'}
            onChange={(key) => setModalTab(key)}
            tabs={tileData.tabs.map((tab) => ({ key: tab.id, label: tab.label }))}
          />
          <DateFilter
            dateFrom={localDateRange.dateFrom ?? undefined}
            dateTo={localDateRange.dateTo ?? undefined}
            onChange={(fromDate, toDate) => setLocalDateRange({ dateFrom: fromDate, dateTo: toDate })}
          />
        </div>
        <div style={{ height: '70vh' }}>
          <RevenueQuery
            query={tileData.query}
            showIntervalSelect={true}
            tileId={modalTileId}
          />
        </div>
      </div>
    </LemonModal>
  )
} 