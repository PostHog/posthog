import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { autoCaptureEventToDescription } from 'lib/utils'
import { memo, MutableRefObject } from 'react'
import {
    InspectorListItemAnnotation,
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
    item: InspectorListItemComment | InspectorListItemEvent | InspectorListItemAnnotation
    endTimeMs: number
    zIndex: number
    onClick: (e: React.MouseEvent) => void
}): JSX.Element | null {
    const isEventItem = (
        x: InspectorListItemComment | InspectorListItemEvent | InspectorListItemAnnotation
    ): x is InspectorListItemEvent => 'event' in x.data
    const isCommentItem = (
        x: InspectorListItemComment | InspectorListItemEvent | InspectorListItemAnnotation
    ): x is InspectorListItemComment => 'comment' in x.data
    const isAnnotationItem = (
        x: InspectorListItemComment | InspectorListItemEvent | InspectorListItemAnnotation
    ): x is InspectorListItemAnnotation => 'content' in x.data
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
                    : isCommentItem(item)
                    ? item.data.comment
                    : isAnnotationItem(item)
                    ? item.data.content ?? undefined
                    : undefined
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
                ) : isCommentItem(item) ? (
                    <span className="font-medium">{item.data.comment}</span>
                ) : isAnnotationItem(item) ? (
                    <span className="font-medium">{item.data.content}</span>
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
        hoverRef,
    }: {
        seekbarItems: (InspectorListItemEvent | InspectorListItemComment | InspectorListItemAnnotation)[]
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
