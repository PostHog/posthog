import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { uuid } from 'lib/utils'
import { WatchNextList, WatchNextListProps } from 'scenes/project-homepage/WatchNextPanel'

import { SessionRecordingType } from '~/types'

function asRecording(param: Partial<SessionRecordingType>): SessionRecordingType {
    return {
        id: '0',
        person: {
            distinct_ids: [uuid()],
            properties: {},
        },
        activity_score: 0,
        recording_duration: 0,
        matching_events: [],
        viewed: false,
        start_time: '2024-11-01 12:34',
        end_time: '2024-11-01 13:34',
        snapshot_source: 'web',
        ...param,
    }
}

type Story = StoryObj<typeof WatchNextList>
const meta: Meta<typeof WatchNextList> = {
    title: 'Replay/Watch Next Panel',
    decorators: [],
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}
export default meta

const Template: StoryFn<typeof WatchNextList> = ({ ...props }: Partial<WatchNextListProps>) => {
    return (
        <WatchNextList
            recordingsOptIn={props.recordingsOptIn ?? true}
            sessionRecordings={props.sessionRecordings || []}
            loading={props.loading || false}
        />
    )
}

export const Empty: Story = Template.bind({})
Empty.args = {}

export const Disabled: Story = Template.bind({})
Disabled.args = {
    recordingsOptIn: false,
}

export const Loading: Story = Template.bind({})
Loading.args = {
    loading: true,
}

export const Scores: Story = Template.bind({})
Scores.args = {
    sessionRecordings: [
        asRecording({
            activity_score: 99,
        }),
        asRecording({
            activity_score: 75,
        }),
        asRecording({
            activity_score: 50,
        }),
        asRecording({
            activity_score: 25,
        }),
        asRecording({
            activity_score: 5,
        }),
    ],
}
