import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { InspectorListItemSimilarEvents } from '../playerInspectorLogic'
import { ItemEvent } from './ItemEvent'
import { PlayerInspectorListItem } from './PlayerInspectorListItem'

export function ItemSimilarEvents({ item }: { item: InspectorListItemSimilarEvents }): JSX.Element {
    return (
        <div className="w-full text-xs items-center justify-center flex">
            <LemonDivider className="shrink" />
            <div className="flex-1 flex px-2">
                <div className="flex gap-1">
                    <span>{item.events[0].data.event}</span>
                    <span>x</span>
                    <span>{item.count}</span>
                </div>
            </div>
            <LemonDivider className="shrink" />
        </div>
    )
}

export function ItemSimilarEventsDetail({ item }: { item: InspectorListItemSimilarEvents }): JSX.Element {
    // render a list of the events
    return (
        <div>
            {item.events.map((event) => (
                console.log(event)
            ))}
        </div>
    )
}