import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { toSentenceCase } from 'lib/utils'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import {
    InspectorListItemAnnotationComment,
    InspectorListItemComment,
    InspectorListItemNotebookComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { urls } from 'scenes/urls'

export interface ItemCommentProps {
    item: InspectorListItemComment
}

function ItemNotebookComment({ item }: { item: InspectorListItemNotebookComment }): JSX.Element {
    return (
        <div data-attr="item-notebook-comment" className="font-light w-full">
            <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer">
                <div className="font-medium truncate">{item.data.comment}</div>
            </div>
        </div>
    )
}

function ItemAnnotationComment({ item }: { item: InspectorListItemAnnotationComment }): JSX.Element {
    return (
        <div data-attr="item-annotation-comment" className="font-light w-full">
            <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer">
                <div className="font-medium truncate">{item.data.content}</div>
            </div>
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

            <div className="p-2 text-xs border-t">
                <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer truncate">
                    <div className="font-medium shrink-0">{item.data.comment}</div>
                </div>
            </div>
        </div>
    )
}

function ItemCommentAnnotationDetail({ item }: { item: InspectorListItemAnnotationComment }): JSX.Element {
    return (
        <div data-attr="item-annotation-comment" className="font-light w-full">
            <div className="px-2 py-1 text-xs border-t w-full flex justify-end">
                <div>Annotation scope: {toSentenceCase(item.data.scope)}</div>
                <LemonButton type="secondary" to={urls.annotation(item.data.id)} size="xsmall">
                    Edit annotation
                </LemonButton>
            </div>

            <div className="p-2 text-xs border-t">
                <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer truncate">
                    <div className="font-medium shrink-0">{item.data.content}</div>
                </div>
            </div>
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
