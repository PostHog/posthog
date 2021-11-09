// Recordings.stories.tsx
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

// import the main component of the scene
import { SessionsRecordings } from '../SessionRecordings'

// import the `getReduxState()` output for all the variations you wish to show
import state from './recordings.json'

// some metadata and optional parameters
export default {
    title: 'PostHog/Scenes/Recordings',
} as Meta

// export more stories with different state
export const Default = keaStory(SessionsRecordings, state)
