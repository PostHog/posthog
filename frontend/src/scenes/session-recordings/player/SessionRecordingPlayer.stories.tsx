import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Realm } from '~/types'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useStorybookMocks } from '~/mocks/browser'
import { SessionRecordingPlayer, SessionRecordingPlayerProps } from './SessionRecordingPlayer'
import { useRef } from 'react'
import { uuid } from 'lib/utils'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'

export default {
    title: 'Components/Replay/Player',
    component: SessionRecordingPlayer,
} as ComponentMeta<typeof SessionRecordingPlayer>

const commonProps = {
    sessionRecordingId: 'storybook',
    playerKey: 'storybook',
    autoPlay: false,
}

const Template: ComponentStory<typeof SessionRecordingPlayer> = (
    args: SessionRecordingPlayerProps & {
        sessionRecordingId?: string
        playerKey?: string
    }
) => {
    const idRef = useRef(uuid())

    const props: SessionRecordingPlayerProps = {
        ...args,
        sessionRecordingId: idRef.current,
        playerKey: `storybook-${idRef.current}`,
    }

    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                realm: Realm.Cloud,
            },
            '/api/projects/:team/session_recordings/:id/snapshots': recordingSnapshotsJson,
            '/api/projects/:team/session_recordings/:id': recordingMetaJson,
        },
        post: {
            '/api/projects/:team/query': recordingEventsJson,
        },
    })

    return (
        <div className="h-120">
            <SessionRecordingPlayer {...props} />
        </div>
    )
}

export const Player_ = (): JSX.Element => {
    return <Template {...commonProps} autoPlay />
}

export const NoAutoPlay = (): JSX.Element => {
    return <Template {...commonProps} />
}

export const NoInspector = (): JSX.Element => {
    return <Template {...commonProps} noInspector />
}

export const FrameOnly = (): JSX.Element => {
    return <Template {...commonProps} noControls noMeta noInspector noBorder />
}
