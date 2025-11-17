import { Meta, StoryFn } from '@storybook/react'

import { RecordingRow } from 'scenes/session-recordings/components/RecordingRow'

import { SessionRecordingType } from '~/types'

function asRecording(param: Partial<SessionRecordingType>): SessionRecordingType {
    return {
        id: '0',
        person: {
            distinct_ids: ['a distinct id'],
            properties: {},
        },
        activity_score: 0,
        recording_duration: 120, // 2 minutes
        matching_events: [],
        viewed: false,
        viewers: [],
        start_time: '2024-11-01 12:34',
        end_time: '2024-11-01 13:34',
        snapshot_source: 'web',
        click_count: 10,
        keypress_count: 20,
        start_url: 'https://example.com',
        console_error_count: 0,
        expiry_time: '2024-11-21 13:34',
        recording_ttl: 20,
        ...param,
    }
}

const meta: Meta<typeof RecordingRow> = {
    title: 'Home/RecordingRow',
    component: RecordingRow,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}
export default meta

export const Default: StoryFn<typeof RecordingRow> = () => {
    const recordings = [
        { activity_score: 99 },
        { activity_score: 75 },
        { activity_score: 50 },
        { activity_score: 25 },
        { activity_score: 5 },
        { activity_score: 0 },
    ]

    return (
        <div className="flex flex-col gap-2 p-4">
            {recordings.map((params, index) => (
                <div key={index} className="border rounded p-2">
                    <RecordingRow recording={asRecording(params)} />
                </div>
            ))}
        </div>
    )
}
