import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

export const RevenueAnalyticsHealthCheck = (): JSX.Element | null => {
  const { isStripeConnected } = useValues(revenueAnalyticsLogic)

  if (!isStripeConnected) {
    return (
      <LemonBanner
        type="info"
        className="my-4"
        action={{
          children: 'Learn more',
          to: 'https://posthog.com/docs/integrate/stripe',
          targetBlank: true,
        }}
      >
        <div>
          <h3 className="mb-2">Connect your Stripe account to see revenue analytics</h3>
          <p>
            Revenue Analytics requires a connection to your Stripe account to display subscription data,
            revenue metrics, and customer information. Connect your Stripe account to get started.
          </p>
        </div>
      </LemonBanner>
    )
  }

  return null
} 