import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { memo, MutableRefObject } from 'react'
import {
    InspectorListItem,
    InspectorListItemComment,
    InspectorListItemEvent,
    InspectorListItemNotebookComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { UserActivity } from './UserActivity'

function isEventItem(x: InspectorListItem): x is InspectorListItemEvent {
    return 'data' in x && !!x.data && 'event' in x.data
}

function isNotebookComment(x: InspectorListItem): x is InspectorListItemNotebookComment {
    return x.type === 'comment' && x.source === 'notebook'
}

function PlayerSeekbarTick({
    item,
    endTimeMs,
    zIndex,
    onClick,
}: {
    item: InspectorListItemComment | InspectorListItemEvent
    endTimeMs: number
    zIndex: number
    onClick: (e: React.MouseEvent) => void
}): JSX.Element | null {
    const position = (item.timeInRecording / endTimeMs) * 100

    if (position < 0 || position > 100) {
        return null
    }

    return (
        <div
            className={clsx('PlayerSeekbarTick', item.highlightColor && `PlayerSeekbarTick--${item.highlightColor}`)}
            title={
                isEventItem(item)
                    ? item.data.event
                    : isNotebookComment(item)
                    ? item.data.comment
                    : item.data.content ?? undefined
            }
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: `${position}%`,
                zIndex: zIndex,
            }}
            onClick={onClick}
        >
            <div className="PlayerSeekbarTick__info">
                {isEventItem(item) ? (
                    <>
                        {item.data.event === '$autocapture' ? (
                            <>{autoCaptureEventToDescription(item.data)}</>
                        ) : (
                            <PropertyKeyInfo
                                className="font-medium"
                                disableIcon
                                disablePopover
                                ellipsis={true}
                                type={TaxonomicFilterGroupType.Events}
                                value={item.data.event}
                            />
                        )}
                        {item.data.event === '$pageview' &&
                        (item.data.properties.$pathname || item.data.properties.$current_url) ? (
                            <span className="ml-2 opacity-75">
                                {item.data.properties.$pathname || item.data.properties.$current_url}
                            </span>
                        ) : null}
                    </>
                ) : isNotebookComment(item) ? (
                    item.data.comment
                ) : (
                    item.data.content
                )}
            </div>
            <div className="PlayerSeekbarTick__line" />
        </div>
    )
}

export const PlayerSeekbarTicks = memo(
    function PlayerSeekbarTicks({
        seekbarItems,
        endTimeMs,
        seekToTime,
        hoverRef,
    }: {
        seekbarItems: (InspectorListItemEvent | InspectorListItemComment)[]
        endTimeMs: number
        seekToTime: (timeInMilliseconds: number) => void
        hoverRef: MutableRefObject<HTMLDivElement | null>
    }): JSX.Element {
        return (
            <div className="PlayerSeekbarTicks">
                <UserActivity hoverRef={hoverRef} />
                {seekbarItems.map((item, i) => {
                    return (
                        <PlayerSeekbarTick
                            key={item.data.id}
                            item={item}
                            endTimeMs={endTimeMs}
                            zIndex={i + (item.highlightColor ? 1000 : 0)}
                            onClick={(e) => {
                                e.stopPropagation()
                                seekToTime(item.timeInRecording)
                            }}
                        />
                    )
                })}
            </div>
        )
    },
    (prev, next) => {
        const seekbarItemsAreEqual =
            prev.seekbarItems.length === next.seekbarItems.length &&
            prev.seekbarItems.every((item, i) => item.data.id === next.seekbarItems[i].data.id)

        return seekbarItemsAreEqual && prev.endTimeMs === next.endTimeMs && prev.seekToTime === next.seekToTime
    }
)
