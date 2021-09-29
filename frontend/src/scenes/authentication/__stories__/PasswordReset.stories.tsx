// PasswordReset.stories.tsx
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the main component of the scene
import { PasswordReset } from '../PasswordReset'

// import the `getReduxState()` output for all the variations you wish to show
import initialState from './reset-initial.json'
import noEmailState from './reset-no-email.json'
//import cloudState from './login-cloud.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Authentication/Password reset',
} as Meta

// export more stories with different state
export const Initial = keaStory(PasswordReset, initialState)
export const NoEmail = keaStory(PasswordReset, noEmailState)
//export const Cloud = keaStory(PasswordReset, cloudState)
