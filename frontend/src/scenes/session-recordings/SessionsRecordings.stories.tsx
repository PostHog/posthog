import { Meta } from '@storybook/react'
import recordings from './__mocks__/recordings.json'
import { useEffect } from 'react'
import { mswDecorator } from '~/mocks/browser'
import { combineUrl, router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

export default {
    title: 'Scenes-App/Recordings',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        testOptions: { skip: true }, // FIXME: Start taking snapshots once the stories no longer crash
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/session_recordings': { results: recordings },
                '/api/projects/:team/session_recordings/:id/snapshots': { result: recordingSnapshotsJson },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
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

export function Recording(): JSX.Element {
    useEffect(() => {
        router.actions.push(
            combineUrl(urls.sessionRecordings(), undefined, { sessionRecordingId: recordings[0].id }).url
        )
    }, [])
    return <App />
}

export function NewRecording(): JSX.Element {
    return (
        <div>
            <SessionRecordingPlayer sessionRecordingId={recordings[0].id} playerKey={'storybook'} />
        </div>
    )
}
