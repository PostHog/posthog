import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import {
    ItemAppState,
    ItemAppStateDetail,
    ItemAppStateProps,
} from 'scenes/session-recordings/player/inspector/components/ItemConsoleLog'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof ItemAppState>
const meta: Meta<typeof ItemAppState> = {
    title: 'Components/PlayerInspector/ItemConsole',
    component: ItemAppState,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

const BasicTemplate: StoryFn<typeof ItemAppState> = (props: Partial<ItemAppStateProps>) => {
    const propsToUse = props as ItemAppStateProps

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '12345' }}>
            <div className="flex flex-col gap-2 min-w-96">
                <h3>Collapsed</h3>
                <ItemAppState {...propsToUse} />
                <LemonDivider />
                <h3>Expanded</h3>
                <ItemAppStateDetail {...propsToUse} />
            </div>
        </BindLogic>
    )
}

export const AppStateItem: Story = BasicTemplate.bind({})
AppStateItem.args = {
    item: {
        timestamp: dayjs('2019-01-30'),
        timeInRecording: 123,
        search: 'some text',
        type: 'app-state',
        action: 'USER_LOGGED_IN',
        stateEvent: {
            prevState: { user: null, nestedJson: { a: 1, b: { c: 2 } } },
            payload: { user: { id: 1, name: 'John Doe' }, nestedJson: { a: 1, b: { c: 3 } } },
            changedState: { user: { id: 1, name: 'John Doe' }, nestedJson: { b: { c: 3 } } },
        },
        key: 'id',
    },
}

/** keep support for these until Oct 2026 */
export const OGFormatAppStateItem: Story = BasicTemplate.bind({})
OGFormatAppStateItem.args = {
    item: {
        timestamp: dayjs('2019-01-30'),
        timeInRecording: 123,
        search: 'some text',
        type: 'app-state',
        action: 'USER_LOGGED_IN',
        stateEvent: {
            prevState: { user: null },
            payload: { user: { id: 1, name: 'John Doe' } },
            nextState: { user: { id: 1, name: 'John Doe' } },
        },
        key: 'id',
    },
}

/** keep support for these until Oct 2026
 * mixed format is "impossible" in practice, but this is just to ensure backwards compatibility
 * */
export const MixedFormatAppStateItem: Story = BasicTemplate.bind({})
MixedFormatAppStateItem.args = {
    item: {
        timestamp: dayjs('2019-01-30'),
        timeInRecording: 123,
        search: 'some text',
        type: 'app-state',
        action: 'USER_LOGGED_IN',
        stateEvent: {
            prevState: { user: null },
            payload: { user: { id: 1, name: 'John Doe' } },
            nextState: { user: { id: 1, name: 'John Doe' } },
            changedState: { user: { id: 1, name: 'John Doe' } },
        },
        key: 'id',
    },
}
