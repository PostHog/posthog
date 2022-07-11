import { Meta } from '@storybook/react'
import recordings from './__mocks__/recordings.json'
import React, { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'

export default {
    title: 'Scenes-App/Recordings',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:projectId/session_recordings': { results: recordings },
            },
        }),
    ],
} as Meta

export function RecordingsList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.sessionRecordings())
    }, [])
    return <App />
}
