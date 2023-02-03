import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { IconUnfoldLess, IconUnfoldMore, IconInfo } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { range } from 'lib/utils'
import React, { Fragment } from 'react'
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

export type SessionRecordingsListProps = {
    listKey: string
    title: React.ReactNode
    titleRight?: React.ReactNode
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
}

export function SessionRecordingsList({
    listKey,
    titleRight,
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
}: SessionRecordingsListProps): JSX.Element {
    const { reportRecordingListVisibilityToggled } = useActions(eventUsageLogic)

    const logic = sessionRecordingsListPropertiesLogic({
        key: listKey,
        sessionIds: recordings?.map((r) => r.id) ?? [],
    })
    const { sessionRecordingIdToProperties, sessionRecordingsPropertiesResponseLoading } = useValues(logic)

    const titleContent = (
        <span className="font-bold uppercase text-xs my-1 tracking-wide flex-1 flex gap-1 items-center">
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

    return (
        <div
            className={clsx('flex flex-col w-full border rounded bg-light', className, {
                'border-dashed': !recordings?.length,
                'overflow-hidden': recordings?.length,
            })}
        >
            <div className="shrink-0 relative flex justify-between items-center p-1 gap-1">
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
                    <span className="px-2 py-1">{titleContent}</span>
                )}
                {titleRight}
                <LemonTableLoader loading={loading} />
            </div>
            {!collapsed ? (
                recordings?.length ? (
                    <ul className="overflow-y-auto border-t">
                        {recordings.map((rec, i) => (
                            <Fragment key={rec.id}>
                                {i > 0 && <div className="border-t" />}
                                <SessionRecordingPlaylistItem
                                    recording={rec}
                                    recordingProperties={sessionRecordingIdToProperties[rec.id]}
                                    recordingPropertiesLoading={sessionRecordingsPropertiesResponseLoading}
                                    onClick={() => onRecordingClick(rec)}
                                    onPropertyClick={onPropertyClick}
                                    isActive={activeRecordingId === rec.id}
                                />
                            </Fragment>
                        ))}
                    </ul>
                ) : loading ? (
                    <>
                        {range(loadingSkeletonCount).map((i) => (
                            <SessionRecordingPlaylistItemSkeleton key={i} />
                        ))}
                    </>
                ) : (
                    <div className="p-3 text-sm text-muted-alt border-t border-dashed">{empty || info}</div>
                )
            ) : null}
        </div>
    )
}
