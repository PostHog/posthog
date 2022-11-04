import { useEffect } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Exporter } from './Exporter'
import { insight, dashboard } from '~/exporter/__mocks__/Exporter.mocks'
import { mswDecorator } from '~/mocks/browser'
import recordings from 'scenes/session-recordings/__mocks__/recordings.json'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'

export default {
    title: 'Exporter/Exporter',
    component: Exporter,
    args: {
        type: 'embed',
        whitelabel: false,
        noHeader: false,
        legend: false,
    },
    parameters: {
        docs: {
            inlineStories: false,
            iframeHeight: 400,
            source: { state: 'close' },
        },
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:projectId/session_recordings': { results: recordings },
                '/api/projects/:team/session_recordings/:id/snapshots': (req) => {
                    console.log('MADE FETCH', req)
                    return [200, { result: recordingSnapshotsJson }]
                },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        }),
    ],
} as ComponentMeta<typeof Exporter>

const Template: ComponentStory<typeof Exporter> = (props) => {
    useEffect(() => {
        document.body.className = ''
        document.documentElement.className = `export-type-${props.type}`
    }, [props.type])
    return (
        <div className={`storybook-export-type-${props.type}`}>
            <Exporter {...props} />
        </div>
    )
}

export const Insight = Template.bind({})
Insight.args = { insight }

export const Dashboard = Template.bind({})
Dashboard.args = { dashboard }

export const Recording = Template.bind({})
Recording.args = { recording: recordings[0] }
