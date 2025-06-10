import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { now } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import {
    ItemComment,
    ItemCommentDetail,
    ItemCommentProps,
} from 'scenes/session-recordings/player/inspector/components/ItemComment'
import {
    InspectorListItemAnnotationComment,
    InspectorListItemNotebookComment,
    RecordingComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { mswDecorator } from '~/mocks/browser'
import { AnnotationScope, AnnotationType } from '~/types'

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

function makeNotebookItem(
    itemOverrides: Partial<InspectorListItemNotebookComment> = {},
    dataOverrides: Partial<RecordingComment> = {}
): InspectorListItemNotebookComment {
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
        source: 'notebook',
        search: '',
        ...itemOverrides,
    }
}

function makeAnnotationItem(
    itemOverrides: Partial<InspectorListItemAnnotationComment> = {},
    dataOverrides: Partial<AnnotationType> = {}
): InspectorListItemAnnotationComment {
    return {
        data: {
            id: 0,
            created_at: now(),
            date_marker: now(),
            updated_at: now().toISOString(),
            scope: AnnotationScope.Project,
            content: '🪓😍🪓😍🪓😍🪓😍',
            ...dataOverrides,
        },
        timeInRecording: 0,
        timestamp: now(),
        type: 'comment',
        source: 'annotation',
        search: '',
        ...itemOverrides,
    }
}

const BasicTemplate: StoryFn<typeof ItemComment> = (props: Partial<ItemCommentProps>) => {
    props.item = props.item || makeNotebookItem()

    const propsToUse = props as ItemCommentProps

    return (
        <div className="flex flex-col gap-2 min-w-96">
            <h3>Collapsed</h3>
            <ItemComment {...propsToUse} />
            <LemonDivider />
            <h3>Expanded</h3>
            <ItemCommentDetail {...propsToUse} />
            <LemonDivider />
            <h3>Collapsed with overflowing comment</h3>
            <div className="w-52">
                <ItemComment {...propsToUse} />
            </div>
        </div>
    )
}

export const NotebookComment: Story = BasicTemplate.bind({})
NotebookComment.args = {
    item: makeNotebookItem(),
}

export const AnnotationComment: Story = BasicTemplate.bind({})
AnnotationComment.args = {
    item: makeAnnotationItem(),
}
