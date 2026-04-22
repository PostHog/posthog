import type { Meta, StoryObj } from '@storybook/react'
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

type Story = StoryObj<ItemConsoleLogProps>
const meta: Meta<ItemConsoleLogProps> = {
    title: 'Components/PlayerInspector/ItemConsole',
    component: ItemConsoleLog,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
    render: (props) => {
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
    },
}
export default meta

const baseData = {
    timestamp: dayjs('2019-01-30').valueOf(),
    windowId: 1,
    windowNumber: 1,
    level: 'log' as const,
    content:
        'This log message is very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very, very long',
}

const baseItem = {
    data: baseData,
    timestamp: dayjs('2019-01-30'),
    timeInRecording: 123,
    search: 'some text',
    type: 'console' as const,
    key: 'some-key',
}

export const ConsoleLogItem: Story = {
    args: {
        item: baseItem,
        groupCount: 12,
        groupedItems: Array.from({ length: 12 }, (_, i) => ({
            ...baseItem,
            key: `console-${i}`,
            timeInRecording: 123 + i * 500,
        })),
    },
}
