import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { InspectorListItemComment } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

export interface ItemCommentProps {
    item: InspectorListItemComment
    expanded: boolean
}

export function ItemComment({ item, expanded }: ItemCommentProps): JSX.Element {
    const { selectNotebook } = useActions(notebookPanelLogic)

    return (
        <div data-attr="item-comment" className="font-light w-full">
            {expanded ? (
                <div className="px-2 py-1 text-xs border-t w-full flex justify-end">
                    <LemonButton
                        type="secondary"
                        onClick={(e) => {
                            selectNotebook(item.data.notebookShortId)
                            e.stopPropagation()
                            e.preventDefault()
                        }}
                    >
                        Continue in {item.data.notebookTitle}
                    </LemonButton>
                </div>
            ) : (
                <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer">
                    <div className="font-medium truncate">{item.data.comment}</div>
                </div>
            )}

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer truncate">
                        <div className="font-medium shrink-0">{item.data.comment}</div>
                    </div>
                </div>
            )}
        </div>
    )
}
