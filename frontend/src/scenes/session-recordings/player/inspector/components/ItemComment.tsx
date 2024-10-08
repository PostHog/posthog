import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { InspectorListItemComment } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

export interface ItemCommentProps {
    item: InspectorListItemComment
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

export function ItemComment({ item, expanded, setExpanded }: ItemCommentProps): JSX.Element {
    const { selectNotebook } = useActions(notebookPanelLogic)

    return (
        <div data-attr="item-comment">
            <LemonButton noPadding onClick={() => setExpanded(!expanded)} fullWidth className="font-normal">
                {expanded ? (
                    <div className="p-2 text-xs border-t w-full flex justify-end">
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
                    <div className="flex flex-row w-full justify-between gap-2 items-center p-2 text-xs cursor-pointer">
                        <div className="font-medium truncate">{item.data.comment}</div>
                    </div>
                )}
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <div className="flex flex-row w-full justify-between gap-2 items-center p-2 text-xs cursor-pointer truncate">
                        <div className="font-medium shrink-0">{item.data.comment}</div>
                    </div>
                </div>
            )}
        </div>
    )
}
