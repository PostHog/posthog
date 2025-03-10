import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useState } from 'react'

import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

export const RevenueAnalyticsFilters = (): JSX.Element => {
  const { dateRange, isStripeConnected } = useValues(revenueAnalyticsLogic)
  const { setDateRange, connectStripe } = useActions(revenueAnalyticsLogic)
  const [isDateFilterOpen, setIsDateFilterOpen] = useState(false)

  return (
    <div className="flex flex-wrap gap-2 items-center justify-between">
      <div className="flex flex-wrap gap-2 items-center">
        <LemonButton
          type="secondary"
          size="small"
          icon={<IconCalendar />}
          onClick={() => setIsDateFilterOpen(!isDateFilterOpen)}
        >
          {dateRange.dateFrom && dateRange.dateTo
            ? `${dateRange.dateFrom} - ${dateRange.dateTo}`
            : 'Date range'}
        </LemonButton>
        <DateFilter
          dateFrom={dateRange.dateFrom ?? undefined}
          dateTo={dateRange.dateTo ?? undefined}
          onChange={(fromDate, toDate) => setDateRange(fromDate, toDate)}
          isDateFilterOpen={isDateFilterOpen}
          setIsDateFilterOpen={setIsDateFilterOpen}
        />

        <LemonDivider vertical />

        <div>
          <LemonLabel>Currency</LemonLabel>
          <LemonSelect
            size="small"
            options={[
              { value: 'USD', label: 'USD ($)' },
              { value: 'EUR', label: 'EUR (€)' },
              { value: 'GBP', label: 'GBP (£)' },
            ]}
            value="USD"
            onChange={() => { }}
          />
        </div>
      </div>

      <div>
        {!isStripeConnected ? (
          <LemonButton
            type="primary"
            onClick={() => connectStripe()}
          >
            Connect Stripe
          </LemonButton>
        ) : (
          <LemonButton
            type="secondary"
            icon={<IconRefresh />}
            onClick={() => { }}
          >
            Refresh data
          </LemonButton>
        )}
      </div>
    </div>
  )
} 