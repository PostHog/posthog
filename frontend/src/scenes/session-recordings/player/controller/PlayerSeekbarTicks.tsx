import clsx from 'clsx'
import posthog from 'posthog-js'
import React, { MutableRefObject, memo } from 'react'

import { IconComment } from '@posthog/icons'

import { TextContent } from 'lib/components/Cards/TextCard/TextCard'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { RichContentPreview } from 'lib/lemon-ui/LemonRichContent/LemonRichContentEditor'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { autoCaptureEventToDescription } from 'lib/utils'
import {
    InspectorListItem,
    InspectorListItemComment,
    InspectorListItemEvent,
    InspectorListItemNotebookComment,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { isSingleEmoji } from 'scenes/session-recordings/utils'

import { UserActivity } from './UserActivity'

function isEventItem(x: InspectorListItem): x is InspectorListItemEvent {
    return 'data' in x && !!x.data && 'event' in x.data
}

function isNotebookComment(x: InspectorListItem): x is InspectorListItemNotebookComment {
    if (x.type !== 'comment') {
        return false
    }
    return 'source' in x && x.source === 'notebook'
}

function isComment(x: InspectorListItem): x is InspectorListItemComment {
    if (x.type !== 'comment') {
        return false
    }
    return 'source' in x && x.source === 'comment'
}

function isAnyComment(x: InspectorListItem): x is InspectorListItemComment | InspectorListItemNotebookComment {
    return x.type === 'comment'
}

function isEmojiComment(x: InspectorListItem): x is InspectorListItemComment {
    return isComment(x) && !!x.data.item_context?.is_emoji && !!x.data.content && isSingleEmoji(x.data.content)
}

function PlayerSeekbarTick({
    item,
    endTimeMs,
    zIndex,
    onClick,
}: {
    item: InspectorListItemComment | InspectorListItemNotebookComment | InspectorListItemEvent
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
                delayMs={10}
                onOpen={() => {
                    posthog.capture('player seekbar tick tooltip shown', {
                        item_type: item.type,
                        ...(isEventItem(item) && { event: item.data.event }),
                    })
                }}
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
                            {item.data.rich_content ? (
                                <RichContentPreview content={item.data.rich_content} className="rounded-none" />
                            ) : (
                                <TextContent
                                    text={item.data.content ?? ''}
                                    data-attr="PlayerSeekbarTicks--text-content"
                                />
                            )}
                            <ProfilePicture user={item.data.created_by} showName size="md" type="person" />{' '}
                        </div>
                    )
                }
            >
                {isEmojiComment(item) ? (
                    <div className="PlayerSeekbarTick__emoji">{item.data.content}</div>
                ) : isAnyComment(item) ? (
                    <div className="PlayerSeekbarTick__comment">
                        <IconComment />
                    </div>
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
        seekbarItems: (InspectorListItemEvent | InspectorListItemComment | InspectorListItemNotebookComment)[]
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
