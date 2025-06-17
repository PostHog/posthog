import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { largeRecordingJSONL } from 'scenes/session-recordings/__mocks__/large_recording_blob_one'
import largeRecordingEventsJson from 'scenes/session-recordings/__mocks__/large_recording_load_events_one.json'
import largeRecordingMetaJson from 'scenes/session-recordings/__mocks__/large_recording_meta.json'
import largeRecordingWebVitalsEventsPropertiesJson from 'scenes/session-recordings/__mocks__/large_recording_web_vitals_props.json'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator, setFeatureFlags } from '~/mocks/browser'

type Story = StoryObj<typeof PlayerInspector>
const meta: Meta<typeof PlayerInspector> = {
    title: 'Components/PlayerInspector',
    component: PlayerInspector,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations': {
                    count: 1,
                    results: [
                        {
                            id: 21,
                            content: 'about seven seconds in there is this comment which is too long',
                            date_marker: '2024-11-15T09:19:35.620000Z',
                            creation_type: 'USR',
                            dashboard_item: null,
                            dashboard_id: null,
                            dashboard_name: null,
                            insight_short_id: null,
                            insight_name: null,
                            insight_derived_name: null,
                            created_by: {
                                id: 1,
                                uuid: '0196b443-26f4-0000-5d24-b982365fe43d',
                                distinct_id: 'BpwPZw8BGaeISf7DlDprsui5J9DMIYjhE3fTFMJiEMF',
                                first_name: 'fasdadafsfasdadafsfasdadafsfasdadafsfasdadafsfasdadafs',
                                last_name: '',
                                email: 'paul@posthog.com',
                                is_email_verified: false,
                                hedgehog_config: null,
                                role_at_organization: 'data',
                            },
                            created_at: '2025-06-11T13:15:06.976791Z',
                            updated_at: '2025-06-11T13:15:06.977228Z',
                            deleted: false,
                            scope: 'recording',
                            recording_id: '01975ab7-e00e-726f-aada-988b2f7fa053',
                        },
                    ],
                    next: null,
                    previous: null,
                },
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

                    if (body.query.kind === 'HogQLQuery') {
                        if (body.query.query.includes("event in ['$web_vitals']")) {
                            return res(ctx.json(largeRecordingWebVitalsEventsPropertiesJson))
                        }
                        return res(ctx.json(largeRecordingEventsJson))
                    }

                    // default to an empty response or we duplicate information
                    return res(ctx.json({ results: [] }))
                },
            },
            patch: {
                '/api/environments/:team_id/session_recordings/:id': (_, res, ctx) => {
                    return res(ctx.json({}))
                },
            },
        }),
    ],
}
export default meta

const BasicTemplate: StoryFn<typeof PlayerInspector> = () => {
    setFeatureFlags([FEATURE_FLAGS.ANNOTATIONS_RECORDING_SCOPE])

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
