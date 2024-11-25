import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { largeRecordingJSONL } from 'scenes/session-recordings/__mocks__/large_recording_blob_one'
import largeRecordingEventsJson from 'scenes/session-recordings/__mocks__/large_recording_load_events_one.json'
import largeRecordingMetaJson from 'scenes/session-recordings/__mocks__/large_recording_meta.json'
import largeRecordingWebVitalsEventsPropertiesJson from 'scenes/session-recordings/__mocks__/large_recording_web_vitals_props.json'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof PlayerInspector>
const meta: Meta<typeof PlayerInspector> = {
    title: 'Components/PlayerInspector',
    component: PlayerInspector,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings/:id': largeRecordingMetaJson,
                '/api/environments/:team_id/session_recordings/:id/snapshots': (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        return res(ctx.text(largeRecordingJSONL))
                    }
                    // with no source requested should return sources
                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob',
                                    start_timestamp: '2023-08-11T12:03:36.097000Z',
                                    end_timestamp: '2023-08-11T12:04:52.268000Z',
                                    blob_key: '1691755416097-1691755492268',
                                },
                            ],
                        },
                    ]
                },
            },
            post: {
                '/api/environments/:team_id/query': (req, res, ctx) => {
                    const body = req.body as Record<string, any>
                    if (body.query.kind === 'EventsQuery' && body.query.properties.length === 1) {
                        return res(ctx.json(largeRecordingEventsJson))
                    }

                    if (body.query.kind === 'HogQLQuery' && body.query.query.includes("event in ['$web_vitals']")) {
                        return res(ctx.json(largeRecordingWebVitalsEventsPropertiesJson))
                    }

                    // default to an empty response or we duplicate information
                    return res(ctx.json({ results: [] }))
                },
            },
        }),
    ],
}
export default meta

const BasicTemplate: StoryFn<typeof PlayerInspector> = () => {
    const dataLogic = sessionRecordingDataLogic({ sessionRecordingId: '12345', playerKey: 'story-template' })
    const { sessionPlayerMetaData } = useValues(dataLogic)

    const { loadSnapshots, loadEvents } = useActions(dataLogic)
    loadSnapshots()

    // TODO you have to call actions in a particular order
    // and only when some other data has already been loaded
    // 🫠
    useEffect(() => {
        loadEvents()
    }, [sessionPlayerMetaData])

    return (
        <div className="flex flex-col gap-2 min-w-96 min-h-120">
            <BindLogic
                logic={sessionRecordingPlayerLogic}
                props={{
                    sessionRecordingId: '12345',
                    playerKey: 'story-template',
                }}
            >
                <PlayerInspector />
            </BindLogic>
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}
