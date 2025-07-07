import { IconInfo } from '@posthog/icons'
import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { toSentenceCase } from 'lib/utils'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import {
    InspectorListItemAnnotationComment,
    InspectorListItemComment,
    InspectorListItemNotebookComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { playerCommentModel } from 'scenes/session-recordings/player/commenting/playerCommentModel'
import { RecordingAnnotationForm } from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'

export interface ItemCommentProps {
    item: InspectorListItemComment
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

function ItemAnnotationComment({ item }: { item: InspectorListItemAnnotationComment }): JSX.Element {
    return (
        <div data-attr="item-annotation-comment" className="font-light w-full px-2 py-1 text-xs truncate text-ellipsis">
            {(item.data.content || '').trim().length > 30 ? (
                <Tooltip title={item.data.content}>{item.data.content}</Tooltip>
            ) : (
                item.data.content
            )}
        </div>
    )
}

function isInspectorListItemNotebookComment(x: ItemCommentProps['item']): x is InspectorListItemNotebookComment {
    return 'comment' in x.data
}

export function ItemComment({ item }: ItemCommentProps): JSX.Element {
    return isInspectorListItemNotebookComment(item) ? (
        <ItemNotebookComment item={item} />
    ) : (
        <ItemAnnotationComment item={item} />
    )
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

function ItemCommentAnnotationDetail({ item }: { item: InspectorListItemAnnotationComment }): JSX.Element {
    const { startCommenting } = useActions(playerCommentModel)
    return (
        <div data-attr="item-annotation-comment" className="font-light w-full flex flex-col gap-y-1">
            <div className="px-2 py-1 text-xs border-t w-full flex justify-between items-center">
                <Tooltip title="Annotations can be scoped to the project or organization, or to individual insights or dashboards. Project and organization scoped annotations are shown in the recording timeline.">
                    <div className="flex flex-row items-center gap-2">
                        <IconInfo className="text-muted text-xs" />
                        Scope: {toSentenceCase(item.data.scope)}
                    </div>
                </Tooltip>
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        void (async () => {
                            // relying on the click here to set the player timestamp
                            // so this shouldn't swallow the click
                            const annotationEditPayload: RecordingAnnotationForm = {
                                annotationId: item.data.id,
                                scope: item.data.scope,
                                content: item.data.content ?? '',
                                dateForTimestamp: item.data.date_marker,
                                recordingId: item.data.recording_id ?? null,
                                timeInRecording: null,
                                timestampInRecording: item.timeInRecording,
                            }
                            startCommenting(annotationEditPayload)
                        })()
                    }}
                    size="xsmall"
                >
                    Edit annotation
                </LemonButton>
            </div>

            <div className="p-2 text-xs border-t cursor-pointer text-wrap">{item.data.content}</div>

            <ProfilePicture
                user={item.data.creation_type === 'GIT' ? { first_name: 'GitHub automation' } : item.data.created_by}
                showName
                size="md"
                type={item.data.creation_type === 'GIT' ? 'bot' : 'person'}
            />
        </div>
    )
}

export function ItemCommentDetail({ item }: ItemCommentProps): JSX.Element {
    return isInspectorListItemNotebookComment(item) ? (
        <ItemCommentNotebookDetail item={item} />
    ) : (
        <ItemCommentAnnotationDetail item={item} />
    )
}
