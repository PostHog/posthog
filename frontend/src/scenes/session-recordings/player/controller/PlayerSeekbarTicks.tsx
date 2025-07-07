import clsx from 'clsx'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { autoCaptureEventToDescription } from 'lib/utils'
import React, { memo, MutableRefObject } from 'react'
import {
    InspectorListItem,
    InspectorListItemAnnotationComment,
    InspectorListItemComment,
    InspectorListItemEvent,
    InspectorListItemNotebookComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { UserActivity } from './UserActivity'
import { isSingleEmoji } from 'scenes/session-recordings/utils'

function isEventItem(x: InspectorListItem): x is InspectorListItemEvent {
    return 'data' in x && !!x.data && 'event' in x.data
}

function isNotebookComment(x: InspectorListItem): x is InspectorListItemNotebookComment {
    return x.type === 'comment' && x.source === 'notebook'
}

function isAnnotationComment(x: InspectorListItem): x is InspectorListItemAnnotationComment {
    return x.type === 'comment' && x.source === 'annotation'
}

function isAnnotationEmojiComment(x: InspectorListItem): x is InspectorListItemAnnotationComment {
    return isAnnotationComment(x) && !!x.data.is_emoji && !!x.data.content && isSingleEmoji(x.data.content)
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
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: `${position}%`,
                zIndex: zIndex,
            }}
            onClick={onClick}
        >
            <Tooltip
                placement="top-start"
                delayMs={50}
                title={
                    isEventItem(item) ? (
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
                        <div className="flex flex-col px-4 py-2 gap-y-2">
                            <div>{item.data.content}</div>
                            <ProfilePicture
                                user={
                                    item.data.creation_type === 'GIT'
                                        ? { first_name: 'GitHub automation' }
                                        : item.data.created_by
                                }
                                showName
                                size="md"
                                type={item.data.creation_type === 'GIT' ? 'bot' : 'person'}
                            />{' '}
                        </div>
                    )
                }
            >
                {isAnnotationEmojiComment(item) ? (
                    <div className="PlayerSeekbarTick__emoji">{item.data.content}</div>
                ) : (
                    <div className="PlayerSeekbarTick__line" />
                )}
            </Tooltip>
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
