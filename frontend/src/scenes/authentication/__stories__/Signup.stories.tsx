// Signup.stories.tsx
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the main component of the scene
import { Signup } from '../Signup'

// import the `getReduxState()` output for all the variations you wish to show
import selfHostedState from './signup-self-hosted.json'
import cloudState from './signup-cloud.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Authentication/Signup',
} as Meta

// export more stories with different state
export const SelfHosted = keaStory(Signup, selfHostedState)
export const Cloud = keaStory(Signup, cloudState)
