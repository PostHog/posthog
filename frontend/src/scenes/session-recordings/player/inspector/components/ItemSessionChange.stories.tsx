import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { dayjs } from 'lib/dayjs'
import {
    ItemSessionChange,
    ItemSessionChangeProps,
} from 'scenes/session-recordings/player/inspector/components/ItemSessionChange'
import { InspectorListSessionChange } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof ItemSessionChange>
const meta: Meta<typeof ItemSessionChange> = {
    title: 'Components/PlayerInspector/ItemSessionChange',
    component: ItemSessionChange,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

const makeSessionChangeItem = (
    tag: '$session_starting' | '$session_ending',
    data: InspectorListSessionChange['data']
): InspectorListSessionChange => {
    return {
        timestamp: dayjs('2024-04-01T12:00:00Z'),
        tag,
        data,
        timeInRecording: 12,
        search: 'starting',
        type: 'session-change',
        key: 'session-change',
    }
}

const BasicTemplate: StoryFn<typeof ItemSessionChange> = (props: ItemSessionChangeProps) => {
    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '12345' }}>
            <div className="flex flex-col gap-2 min-w-96">
                <ItemSessionChange {...props} />
            </div>
        </BindLogic>
    )
}

export const SessionPrevious: Story = BasicTemplate.bind({})

SessionPrevious.args = {
    item: makeSessionChangeItem('$session_starting', { previousSessionId: 'wxyz-5678' }),
}

export const SessionNext: Story = BasicTemplate.bind({})
SessionNext.args = {
    item: makeSessionChangeItem('$session_ending', { nextSessionId: 'abcd-1234' }),
}
