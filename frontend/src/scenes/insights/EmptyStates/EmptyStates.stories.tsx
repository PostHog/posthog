// EmptyStates.stories.tsx
import React from 'react'
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the insight container
import { Insight } from '../Insight'
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
export const EmptyState = keaStory(Insight, emptyState)
export const ErrorState = keaStory(Insight, errorState)
export const TimeoutState = keaStory(Insight, timeoutState)
export const FunelSingleStep = keaStory(Insight, funnelSingleStepState)
export const FunnelInvalidExclusion = keaStory(Insight, funnelInvalidExclusionState)
export const DashboardInsightEmptyState = keaStory(() => <Dashboard id="3" />, dashboardInsightEmptyState)
