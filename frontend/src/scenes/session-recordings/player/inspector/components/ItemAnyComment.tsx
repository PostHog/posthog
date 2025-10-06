import { useActions, useValues } from 'kea'

import { IconPencil, IconTrash } from '@posthog/icons'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { RichContentPreview } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { playerCommentModel } from 'scenes/session-recordings/player/commenting/playerCommentModel'
import { RecordingCommentForm } from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'
import {
    InspectorListItemComment,
    InspectorListItemNotebookComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { sessionRecordingCommentsLogic } from 'scenes/session-recordings/player/sessionRecordingCommentsLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export interface ItemCommentProps {
    item: InspectorListItemComment | InspectorListItemNotebookComment
}

function isInspectorListItemNotebookComment(x: ItemCommentProps['item']): x is InspectorListItemNotebookComment {
    return 'comment' in x.data
}

function ItemNotebookComment({ item }: { item: InspectorListItemNotebookComment }): JSX.Element {
    return (
        <div data-attr="item-notebook-comment" className="font-light w-full px-2 py-1 text-xs truncate text-ellipsis">
            {item.data.comment.trim().length > 30 ? (
                <Tooltip title={item.data.comment}>{item.data.comment}</Tooltip>
            ) : (
                item.data.comment
            )}
        </div>
    )
}

function ItemComment({ item }: { item: InspectorListItemComment }): JSX.Element {
    // lazy but good enough check for markdown image urls
    // we don't want to render markdown in the list row if there's an image since it won't fit
    const hasMarkdownImage = (item.data.content ?? '').includes('![')

    let rowContent = item.data.rich_content ? (
        <RichContentPreview content={item.data.rich_content} className="rounded-none" />
    ) : hasMarkdownImage ? (
        <>{item.data.content ?? ''}</>
    ) : (
        <TextContent text={item.data.content ?? ''} data-attr="item-annotation-comment-title-rendered-content" />
    )

    return (
        <div data-attr="item-annotation-comment" className="font-light w-full px-2 py-1 text-xs truncate text-ellipsis">
            {(item.data.content || '').trim().length > 30 ? (
                <Tooltip
                    title={
                        item.data.rich_content ? (
                            <RichContentPreview content={item.data.rich_content} className="rounded-none" />
                        ) : (
                            <TextContent
                                text={item.data.content ?? ''}
                                data-attr="item-annotation-comment-title-rendered-content"
                            />
                        )
                    }
                >
                    {rowContent}
                </Tooltip>
            ) : (
                rowContent
            )}
        </div>
    )
}

export function ItemAnyComment({ item }: ItemCommentProps): JSX.Element {
    return isInspectorListItemNotebookComment(item) ? <ItemNotebookComment item={item} /> : <ItemComment item={item} />
}

function ItemCommentNotebookDetail({ item }: { item: InspectorListItemNotebookComment }): JSX.Element {
    const { selectNotebook } = useActions(notebookPanelLogic)

    return (
        <div data-attr="item-notebook-comment" className="font-light w-full">
            <div className="px-2 py-1 text-xs border-t w-full flex justify-end">
                <LemonButton
                    type="secondary"
                    onClick={(e) => {
                        selectNotebook(item.data.notebookShortId)
                        e.stopPropagation()
                        e.preventDefault()
                    }}
                    size="xsmall"
                >
                    Continue in {item.data.notebookTitle}
                </LemonButton>
            </div>

            <div className="px-2 py-1 text-xs border-t text-wrap">{item.data.comment}</div>
        </div>
    )
}

function ItemCommentDetail({ item }: { item: InspectorListItemComment }): JSX.Element {
    const { startCommenting } = useActions(playerCommentModel)
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const commentsLogic = sessionRecordingCommentsLogic(logicProps)
    const { deleteComment } = useActions(commentsLogic)

    return (
        <div data-attr="item-annotation-comment" className="font-light w-full flex flex-col gap-y-1">
            <div className="px-2 py-1 text-xs border-t w-full flex justify-end items-center gap-x-1">
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        deleteComment(item.data.id)
                    }}
                    size="xsmall"
                    icon={<IconTrash />}
                >
                    Delete
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        void (async () => {
                            // relying on the click here to set the player timestamp
                            // so this shouldn't swallow the click
                            const commentEditPayload: RecordingCommentForm = {
                                commentId: item.data.id,
                                content: item.data.content ?? '',
                                richContent: item.data.rich_content ?? null,
                                dateForTimestamp: item.timestamp,
                                recordingId: item.data.item_id ?? null,
                                timestampInRecording: item.timeInRecording,
                            }
                            startCommenting(commentEditPayload)
                        })()
                    }}
                    size="xsmall"
                    icon={<IconPencil />}
                >
                    Edit
                </LemonButton>
            </div>

            <div className="p-2 text-xs border-t cursor-pointer text-wrap">
                <TextContent
                    text={item.data.content ?? ''}
                    data-attr="item-annotation-comment-detail-rendered-content"
                />
            </div>

            <ProfilePicture user={item.data.created_by} showName size="md" type="person" />
        </div>
    )
}

export function ItemAnyCommentDetail({ item }: ItemCommentProps): JSX.Element {
    return isInspectorListItemNotebookComment(item) ? (
        <ItemCommentNotebookDetail item={item} />
    ) : (
        <ItemCommentDetail item={item} />
    )
}
