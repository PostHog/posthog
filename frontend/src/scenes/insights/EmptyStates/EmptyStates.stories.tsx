// EmptyStates.stories.tsx
import React from 'react'
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the insight container
import { Insights } from '../Insights'
import { Dashboard } from 'scenes/dashboard/Dashboard'

// import the `getReduxState()` output for all the variations you wish to show
import funnelSingleStepState from './funnel-single-step-state.json'
import funnelInvalidExclusionState from './funnel-invalid-exclusion-state.json'
import emptyState from './empty-state.json'
import errorState from './error-state.json'
import timeoutState from './timeout-state.json'
import dashboardInsightEmptyState from './dashboard-insight-empty-state.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Scenes/Insights/Error states',
} as Meta

// export more stories with different state
export const EmptyState = keaStory(Insights, emptyState)
export const ErrorState = keaStory(Insights, errorState)
export const TimeoutState = keaStory(Insights, timeoutState)
export const FunelSingleStep = keaStory(Insights, funnelSingleStepState)
export const FunnelInvalidExclusion = keaStory(Insights, funnelInvalidExclusionState)
export const DashboardInsightEmptyState = keaStory(() => <Dashboard id="3" />, dashboardInsightEmptyState)
