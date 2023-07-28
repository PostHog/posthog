import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { IconUnfoldLess, IconUnfoldMore, IconInfo } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { range } from 'lib/utils'
import React, { Fragment, useEffect, useRef } from 'react'
import { SessionRecordingType } from '~/types'
import {
    SessionRecordingPlaylistItem,
    SessionRecordingPlaylistItemProps,
    SessionRecordingPlaylistItemSkeleton,
} from './SessionRecordingsPlaylistItem'
import { useActions, useValues } from 'kea'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

const SCROLL_TRIGGER_OFFSET = 100

export type SessionRecordingsListProps = {
    listKey: string
    title: React.ReactNode
    titleRight?: React.ReactNode
    titleActions?: React.ReactNode
    info?: React.ReactNode
    recordings?: SessionRecordingType[]
    onRecordingClick: (recording: SessionRecordingType) => void
    onPropertyClick: SessionRecordingPlaylistItemProps['onPropertyClick']
    activeRecordingId?: SessionRecordingType['id']
    loading?: boolean
    loadingSkeletonCount?: number
    collapsed?: boolean
    onCollapse?: (collapsed: boolean) => void
    empty?: React.ReactNode
    className?: string
    footer?: React.ReactNode
    subheader?: React.ReactNode
    onScrollToStart?: () => void
    onScrollToEnd?: () => void
    draggableHref?: string
}

export function SessionRecordingsList({
    listKey,
    titleRight,
    titleActions,
    recordings,
    collapsed,
    onCollapse,
    title,
    loading,
    loadingSkeletonCount = 1,
    info,
    empty,
    onRecordingClick,
    onPropertyClick,
    activeRecordingId,
    className,
    footer,
    subheader,
    onScrollToStart,
    onScrollToEnd,
    draggableHref,
}: SessionRecordingsListProps): JSX.Element {
    const { reportRecordingListVisibilityToggled } = useActions(eventUsageLogic)
    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)
    const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)

    const titleContent = (
        <span className="font-bold uppercase text-xs my-1 tracking-wide flex gap-1 items-center">
            {title}
            {info ? (
                <Tooltip title={info}>
                    <IconInfo className="text-muted-alt" />
                </Tooltip>
            ) : null}
        </span>
    )

    const setCollapsedWrapper = (val: boolean): void => {
        onCollapse?.(val)
        reportRecordingListVisibilityToggled(listKey, !val)
    }

    const handleScroll =
        onScrollToEnd || onScrollToStart
            ? (e: React.UIEvent<HTMLDivElement>): void => {
                  // If we are scrolling down then check if we are at the bottom of the list
                  if (e.currentTarget.scrollTop > lastScrollPositionRef.current) {
                      const scrollPosition = e.currentTarget.scrollTop + e.currentTarget.clientHeight
                      if (e.currentTarget.scrollHeight - scrollPosition < SCROLL_TRIGGER_OFFSET) {
                          onScrollToEnd?.()
                      }
                  }

                  // Same again but if scrolling to the top
                  if (e.currentTarget.scrollTop < lastScrollPositionRef.current) {
                      if (e.currentTarget.scrollTop < SCROLL_TRIGGER_OFFSET) {
                          onScrollToStart?.()
                      }
                  }

                  lastScrollPositionRef.current = e.currentTarget.scrollTop
              }
            : undefined

    useEffect(() => {
        if (subheader && contentRef.current) {
            contentRef.current.scrollTop = 0
        }
    }, [!!subheader])

    return (
        <div
            className={clsx('flex flex-col w-full bg-bg-light border rounded', className, {
                'border-dashed': !recordings?.length,
                'overflow-hidden': recordings?.length,
            })}
        >
            <DraggableToNotebook href={draggableHref} alwaysDraggable noOverflow>
                <div className="shrink-0 relative flex justify-between items-center p-1 gap-1 whitespace-nowrap">
                    {onCollapse ? (
                        <LemonButton
                            className="flex-1"
                            status="stealth"
                            icon={collapsed ? <IconUnfoldMore /> : <IconUnfoldLess />}
                            size="small"
                            onClick={() => setCollapsedWrapper(!collapsed)}
                        >
                            {titleContent}
                        </LemonButton>
                    ) : (
                        <span className="px-2 py-1 flex flex-1 gap-2">
                            {titleContent}
                            {titleRight}
                        </span>
                    )}
                    {titleActions}
                    <LemonTableLoader loading={loading} />
                </div>
            </DraggableToNotebook>
            {!collapsed ? (
                <div
                    className={clsx('overflow-y-auto border-t ', {
                        'border-dashed': !recordings?.length,
                    })}
                    onScroll={handleScroll}
                    ref={contentRef}
                >
                    {subheader}
                    {recordings?.length ? (
                        <ul>
                            {recordings.map((rec, i) => (
                                <Fragment key={rec.id}>
                                    {i > 0 && <div className="border-t" />}
                                    <SessionRecordingPlaylistItem
                                        recording={rec}
                                        recordingProperties={recordingPropertiesById[rec.id]}
                                        recordingPropertiesLoading={
                                            !recordingPropertiesById[rec.id] && recordingPropertiesLoading
                                        }
                                        onClick={() => onRecordingClick(rec)}
                                        onPropertyClick={onPropertyClick}
                                        isActive={activeRecordingId === rec.id}
                                    />
                                </Fragment>
                            ))}

                            {footer}
                        </ul>
                    ) : loading ? (
                        <>
                            {range(loadingSkeletonCount).map((i) => (
                                <SessionRecordingPlaylistItemSkeleton key={i} />
                            ))}
                        </>
                    ) : (
                        <div className="p-3 text-sm text-muted-alt">{empty || info}</div>
                    )}
                </div>
            ) : null}
        </div>
    )
}
