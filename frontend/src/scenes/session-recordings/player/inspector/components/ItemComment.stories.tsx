import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { now } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import {
    ItemAnyComment,
    ItemAnyCommentDetail,
    ItemCommentProps,
} from 'scenes/session-recordings/player/inspector/components/ItemAnyComment'
import {
    InspectorListItemComment,
    InspectorListItemNotebookComment,
    RecordingComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'
import { CommentType } from '~/types'

type Story = StoryObj<typeof ItemAnyComment>
const meta: Meta<typeof ItemAnyComment> = {
    title: 'Components/PlayerInspector/ItemComment',
    component: ItemAnyComment,
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
        key: 'id',
        ...itemOverrides,
    }
}

function makeCommentItem(
    itemOverrides: Partial<InspectorListItemComment> = {},
    dataOverrides: Partial<CommentType> = {}
): InspectorListItemComment {
    return {
        data: {
            id: '0',
            version: 0,
            created_at: now().toISOString(),
            scope: 'recording',
            content: '🪓😍🪓😍🪓😍🪓😍',
            rich_content: {
                type: 'doc',
                content: [{ type: 'paragraph', content: [{ type: 'text', text: '🪓😍🪓😍🪓😍🪓😍' }] }],
            },
            item_context: {},
            created_by: {
                id: 1,
                uuid: '0196b443-26f4-0000-5d24-b982365fe43d',
                distinct_id: 'BpwPZw8BGaeISf7DlDprsui5J9DMIYjhE3fTFMJiEMF',
                first_name: 'fasdadafsfasdadafsfasdadafsfasdadafsfasdadafsfasdadafs',
                last_name: '',
                email: 'paul@posthog.com',
                is_email_verified: false,
            },
            ...dataOverrides,
        },
        timeInRecording: 0,
        timestamp: now(),
        type: 'comment',
        source: 'comment',
        search: '',
        key: 'id',
        ...itemOverrides,
    }
}

const BasicTemplate: StoryFn<typeof ItemAnyComment> = (props: Partial<ItemCommentProps>) => {
    props.item = props.item || makeNotebookItem()

    const propsToUse = props as ItemCommentProps

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '12345' }}>
            <div className="flex flex-col gap-2 min-w-96">
                <h3>Collapsed</h3>
                <ItemAnyComment {...propsToUse} />
                <LemonDivider />
                <h3>Expanded</h3>
                <ItemAnyCommentDetail {...propsToUse} />
                <LemonDivider />
                <h3>Expanded with overflowing comment</h3>
                <div className="w-52">
                    <ItemAnyCommentDetail
                        {...propsToUse}
                        item={
                            {
                                ...propsToUse.item,
                                data: {
                                    ...propsToUse.item.data,
                                    comment:
                                        'abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz',
                                },
                            } as InspectorListItemNotebookComment
                        }
                    />
                </div>
                <LemonDivider />
                <h3>Collapsed with overflowing comment</h3>
                <div className="w-52">
                    <ItemAnyComment
                        {...propsToUse}
                        item={
                            {
                                ...propsToUse.item,
                                data: {
                                    ...propsToUse.item.data,
                                    comment:
                                        'abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz',
                                },
                            } as InspectorListItemNotebookComment
                        }
                    />
                </div>
            </div>
        </BindLogic>
    )
}

export const NotebookComment: Story = BasicTemplate.bind({})
NotebookComment.args = {
    item: makeNotebookItem(),
}

export const AnnotationComment: Story = BasicTemplate.bind({})
AnnotationComment.args = {
    item: makeCommentItem(),
}
