import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { now } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { ItemComment, ItemCommentProps } from 'scenes/session-recordings/player/inspector/components/ItemComment'
import {
    InspectorListItemComment,
    RecordingComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof ItemComment>
const meta: Meta<typeof ItemComment> = {
    title: 'Components/PlayerInspector/ItemComment',
    component: ItemComment,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

function makeItem(
    itemOverrides: Partial<InspectorListItemComment> = {},
    dataOverrides: Partial<RecordingComment> = {}
): InspectorListItemComment {
    return {
        data: {
            id: 'id',
            notebookShortId: '123',
            notebookTitle: 'My notebook',
            comment: 'the comment on the timestamp in the notebook',
            timeInRecording: 0,
            ...dataOverrides,
        },
        timeInRecording: 0,
        timestamp: now(),
        type: 'comment',
        search: '',
        ...itemOverrides,
    }
}

const BasicTemplate: StoryFn<typeof ItemComment> = (props: Partial<ItemCommentProps>) => {
    props.item = props.item || makeItem()
    props.setExpanded = props.setExpanded || (() => {})

    const propsToUse = props as ItemCommentProps

    return (
        <div className="flex flex-col gap-2 min-w-96">
            <h3>Collapsed</h3>
            <ItemComment {...propsToUse} expanded={false} />
            <LemonDivider />
            <h3>Expanded</h3>
            <ItemComment {...propsToUse} expanded={true} />
            <LemonDivider />
            <h3>Collapsed with overflowing comment</h3>
            <div className="w-52">
                <ItemComment {...propsToUse} expanded={false} />
            </div>
        </div>
    )
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {}
