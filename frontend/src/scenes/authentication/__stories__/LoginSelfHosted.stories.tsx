// Events.stories.tsx
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the main component of the scene
import { Login } from '../Login'

// import the `getReduxState()` output for all the variations you wish to show
import loginState from './login-self-hosted.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Scenes/Login',
} as Meta

// export more stories with different state
export const SelfHosted = keaStory(Login, loginState)
