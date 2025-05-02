import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { memo, MutableRefObject } from 'react'
import {
    InspectorListItemComment,
    InspectorListItemEvent,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { UserActivity } from './UserActivity'

export interface SeekBarItem {
    timeInRecording: number
    highlightColor?: string
    label: string | JSX.Element
    title?: string
    key: string
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
    const data = item.data
    const isEventItem = 'event' in data
    const position = (item.timeInRecording / endTimeMs) * 100

    if (position < 0 || position > 100) {
        return null
    }

    return (
        <div
            className={clsx('PlayerSeekbarTick', item.highlightColor && `PlayerSeekbarTick--${item.highlightColor}`)}
            title={isEventItem ? data.event : data.comment}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: `${position}%`,
                zIndex: zIndex,
            }}
            onClick={onClick}
        >
            <div className="PlayerSeekbarTick__info">
                {isEventItem ? (
                    <>
                        {data.event === '$autocapture' ? (
                            <>{autoCaptureEventToDescription(data)}</>
                        ) : (
                            <PropertyKeyInfo
                                className="font-medium"
                                disableIcon
                                disablePopover
                                ellipsis={true}
                                type={TaxonomicFilterGroupType.Events}
                                value={data.event}
                            />
                        )}
                        {data.event === '$pageview' && (data.properties.$pathname || data.properties.$current_url) ? (
                            <span className="ml-2 opacity-75">
                                {data.properties.$pathname || data.properties.$current_url}
                            </span>
                        ) : null}
                    </>
                ) : (
                    data.comment
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
