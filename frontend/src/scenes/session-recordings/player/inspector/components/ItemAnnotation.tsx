import { InspectorListItemAnnotation } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

export interface ItemAnnotationProps {
    item: InspectorListItemAnnotation
}

export function ItemAnnotation({ item }: ItemAnnotationProps): JSX.Element {
    return (
        <div data-attr="item-annotation" className="font-light w-full">
            <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer">
                <div className="font-medium truncate">{item.data.content}</div>
            </div>
        </div>
    )
}

export function ItemAnnotationDetail({ item }: ItemAnnotationProps): JSX.Element {
    return (
        <div data-attr="item-annotation" className="font-light w-full">
            <div className="p-2 text-xs border-t">
                <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer truncate">
                    <div className="font-medium shrink-0">{item.data.content}</div>
                </div>
            </div>
        </div>
    )
}
