// Login.stories.tsx
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the main component of the scene
import { Login } from '../Login'

// import the `getReduxState()` output for all the variations you wish to show
import selfHostedState from './login-self-hosted.json'
import selfHostedSAMLState from './login-self-hosted-saml.json'
import cloudState from './login-cloud.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Authentication/Login',
} as Meta

// export more stories with different state
export const Cloud = keaStory(Login, cloudState)
export const SelfHosted = keaStory(Login, selfHostedState)
export const SelfHostedWithSAML = keaStory(Login, selfHostedSAMLState)
