import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the main component of the scene
import { BillingSubscribed } from './BillingSubscribed'

// import the `getReduxState()` output for all the variations you wish to show
import successState from './billing-subscribed-success.json'
import failedState from './billing-subscribed-failed.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Scenes/Billing',
} as Meta

// export more stories with different state
export const Subscribed = keaStory(BillingSubscribed, successState)
export const FailedSubscription = keaStory(BillingSubscribed, failedState)
