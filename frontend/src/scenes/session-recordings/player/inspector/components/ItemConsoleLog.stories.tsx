import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import {
    ItemConsoleLog,
    ItemConsoleLogDetail,
    ItemConsoleLogProps,
} from 'scenes/session-recordings/player/inspector/components/ItemConsoleLog'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof ItemConsoleLog>
const meta: Meta<typeof ItemConsoleLog> = {
    title: 'Components/PlayerInspector/ItemConsole',
    component: ItemConsoleLog,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

const BasicTemplate: StoryFn<typeof ItemConsoleLog> = (props: Partial<ItemConsoleLogProps>) => {
    const propsToUse = props as ItemConsoleLogProps

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '12345' }}>
            <div className="flex flex-col gap-2 min-w-96">
                <h3>Collapsed</h3>
                <ItemConsoleLog {...propsToUse} />
                <LemonDivider />
                <h3>Expanded</h3>
                <ItemConsoleLogDetail {...propsToUse} />
            </div>
        </BindLogic>
    )
}

export const ConsoleLogItem: Story = BasicTemplate.bind({})
ConsoleLogItem.args = {
    item: {
        data: {
            timestamp: dayjs('2019-01-30').valueOf(),
            windowId: '12345',
            windowNumber: 1,
            level: 'log',
            content:
                'This log message is very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very long',
            count: 12,
        },
        timestamp: dayjs('2019-01-30'),
        timeInRecording: 123,
        search: 'some text',
        type: 'console',
        key: 'some-key',
    },
}
