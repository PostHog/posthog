import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { autoCaptureEventToDescription, capitalizeFirstLetter } from 'lib/utils'
import { memo } from 'react'

import { InspectorListItemEvent } from '../inspector/playerInspectorLogic'

function PlayerSeekbarTick(props: {
    item: InspectorListItemEvent
    endTimeMs: number
    zIndex: number
    onClick: (e: React.MouseEvent) => void
}): JSX.Element {
    return (
        <div
            className={clsx(
                'PlayerSeekbarTick',
                props.item.highlightColor && `PlayerSeekbarTick--${props.item.highlightColor}`
            )}
            title={props.item.data.event}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: `${(props.item.timeInRecording / props.endTimeMs) * 100}%`,
                zIndex: props.zIndex,
            }}
            onClick={props.onClick}
        >
            <div className="PlayerSeekbarTick__info">
                <PropertyKeyInfo
                    className="font-medium"
                    disableIcon
                    disablePopover
                    ellipsis={true}
                    value={capitalizeFirstLetter(autoCaptureEventToDescription(props.item.data))}
                />
                {props.item.data.event === '$autocapture' ? (
                    <span className="opacity-75 ml-2">(Autocapture)</span>
                ) : null}
                {props.item.data.event === '$pageview' ? (
                    <span className="ml-2 opacity-75">
                        {props.item.data.properties.$pathname || props.item.data.properties.$current_url}
                    </span>
                ) : null}
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
        seekbarItems: InspectorListItemEvent[]
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
