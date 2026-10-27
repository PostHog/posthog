import { useActions, useValues } from 'kea'

import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

import { TodayHighlightRow } from './TodayHighlightRow'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { todayReplayPreviewLogic } from './todayReplayPreviewLogic'
import { TodayReplayRowDetail } from './TodayReplayRowDetail'

export function TodayReplayHighlightRow({
    item,
    position,
    done,
    savedFilterId,
}: {
    item: HighlightItemApi
    position: number
    done: boolean
    savedFilterId: string
}): JSX.Element {
    const logic = todayReplayPreviewLogic({ savedFilterId })
    const { expanded } = useValues(logic)
    const { toggleExpanded } = useActions(logic)
    const { highlightOpened } = useActions(todayHighlightsLogic)
    return (
        <TodayHighlightRow
            item={item}
            position={position}
            done={done}
            expansion={{
                expanded,
                onToggle: toggleExpanded,
                detail: (
                    <TodayReplayRowDetail
                        savedFilterId={savedFilterId}
                        to={item.url ?? ''}
                        onOpen={() => highlightOpened(item, position)}
                    />
                ),
            }}
        />
    )
}
