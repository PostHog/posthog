// Recordings.stories.tsx
import { Meta } from '@storybook/react'
import { SessionsRecordings } from './SessionRecordings'
import recordings from './__mocks__/recordings.json'
import React from 'react'
import { mswDecorator } from '~/mocks/browser'

// some metadata and optional parameters
export default {
    title: 'Scenes/Recordings',
    parameters: { options: { showPanel: false }, viewMode: 'canvas' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/1/session_recordings': { results: recordings },
            },
        }),
    ],
} as Meta

// export more stories with different state
export const Default = (): JSX.Element => <SessionsRecordings />
