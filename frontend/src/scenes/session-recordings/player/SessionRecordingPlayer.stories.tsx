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
    argTypes: {
        noBorder: {
            defaultValue: false,
        },
        noInspector: {
            defaultValue: false,
        },
        noControls: {
            defaultValue: false,
        },
        noMeta: {
            defaultValue: false,
        },
    },
} as ComponentMeta<typeof SessionRecordingPlayer>

const Template: ComponentStory<typeof SessionRecordingPlayer> = (
    args: SessionRecordingPlayerProps & {
        sessionRecordingId?: string
        playerKey?: string
    }
) => {
    const idRef = useRef(uuid())

    const props: SessionRecordingPlayerProps = {
        ...args,
        autoPlay: false,
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

export const Player = Template.bind({})
Player.args = {
    autoPlay: true,
}

export const NoAutoPlay = Template.bind({})
NoAutoPlay.args = {
    autoPlay: true,
}

export const NoInspector = Template.bind({})
NoInspector.args = {
    noInspector: true,
}

export const FrameOnly = Template.bind({})
FrameOnly.args = {
    noControls: true,
    noMeta: true,
    noInspector: true,
    noBorder: true,
}
