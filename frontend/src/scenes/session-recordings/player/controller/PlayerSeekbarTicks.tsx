import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter } from 'lib/utils'
import { memo } from 'react'
import {
    InspectorListItemComment,
    InspectorListItemEvent,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

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
}): JSX.Element {
    const data = item.data
    const isEventItem = 'event' in data
    return (
        <div
            className={clsx('PlayerSeekbarTick', item.highlightColor && `PlayerSeekbarTick--${item.highlightColor}`)}
            title={isEventItem ? data.event : data.comment}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: `${(item.timeInRecording / endTimeMs) * 100}%`,
                zIndex: zIndex,
            }}
            onClick={onClick}
        >
            <div className="PlayerSeekbarTick__info">
                {isEventItem ? (
                    <>
                        <PropertyKeyInfo
                            className="font-medium"
                            disableIcon
                            disablePopover
                            ellipsis={true}
                            value={capitalizeFirstLetter(autoCaptureEventToDescription(data))}
                        />
                        {data.event === '$autocapture' ? <span className="opacity-75 ml-2">(Autocapture)</span> : null}
                        {data.event === '$pageview' ? (
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
    }: {
        seekbarItems: (InspectorListItemEvent | InspectorListItemComment)[]
        endTimeMs: number
        seekToTime: (timeInMilliseconds: number) => void
    }): JSX.Element {
        return (
            <div className="PlayerSeekbarTicks">
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
