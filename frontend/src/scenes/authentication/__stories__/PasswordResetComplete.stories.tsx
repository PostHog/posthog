// PasswordResetComplete.stories.tsx
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the main component of the scene
import { PasswordResetComplete } from '../PasswordResetComplete'

// import the `getReduxState()` output for all the variations you wish to show
import defaultState from './reset-complete.json'
import invalidState from './reset-complete-invalid.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Authentication/Password reset/Complete',
} as Meta

// export more stories with different state
export const Default = keaStory(PasswordResetComplete, defaultState)
export const InvalidLink = keaStory(PasswordResetComplete, invalidState)
