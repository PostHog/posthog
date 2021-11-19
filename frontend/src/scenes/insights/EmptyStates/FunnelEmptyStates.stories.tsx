// EmptyStates.stories.tsx
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the insight container
//import { InsightContainer } from '../InsightContainer'
import { Insights } from '../Insights'

// import the `getReduxState()` output for all the variations you wish to show
import funnelSingleStepState from './funnel-single-step-state.json'
import funnelInvalidExclusionState from './funnel-invalid-exclusion-state.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Scenes/Insights/Funnels',
} as Meta

// export more stories with different state
export const ErrorSingleStep = keaStory(Insights, funnelSingleStepState)
export const ErrorInvalidExclusion = keaStory(Insights, funnelInvalidExclusionState)
