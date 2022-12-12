import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { IconUnfoldLess, IconUnfoldMore, IconInfo } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { range } from 'lib/utils'
import React, { Fragment, useState } from 'react'
import { SessionRecordingType } from '~/types'
import {
    SessionRecordingPlaylistItem,
    SessionRecordingPlaylistItemProps,
    SessionRecordingPlaylistItemSkeleton,
} from './SessionRecordingsPlaylistItem'

export type SessionRecordingsListProps = {
    title: React.ReactNode
    info?: React.ReactNode
    recordings?: SessionRecordingType[]
    onRecordingClick: (recording: SessionRecordingType) => void
    onPropertyClick: SessionRecordingPlaylistItemProps['onPropertyClick']
    activeRecordingId?: SessionRecordingType['id']
    loading?: boolean
    loadingSkeletonCount?: number
    collapsable?: boolean
    empty?: React.ReactNode
}

export function SessionRecordingsList({
    recordings,
    collapsable,
    title,
    loading,
    loadingSkeletonCount = 1,
    info,
    empty,
    onRecordingClick,
    onPropertyClick,
    activeRecordingId,
}: SessionRecordingsListProps): JSX.Element {
    const [collapsed, setCollapsed] = useState(false)

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

    return (
        <div
            className={clsx('flex flex-col w-full border rounded', {
                'border-dashed': !recordings?.length,
                'flex-1': !collapsed && recordings?.length,
                'flex-0': collapsed,
                'overflow-hidden': recordings?.length,
            })}
        >
            <div className="shrink-0 relative flex justify-between items-center p-1 gap-1">
                {collapsable ? (
                    <LemonButton
                        className="flex-1"
                        status="stealth"
                        icon={collapsed ? <IconUnfoldMore /> : <IconUnfoldLess />}
                        size="small"
                        onClick={() => setCollapsed(!collapsed)}
                    >
                        {titleContent}
                    </LemonButton>
                ) : (
                    titleContent
                )}
                {/* <span className="rounded p-1 px-2 text-xs bg-border-light">5 of 100</span> */}
            </div>
            {!collapsed ? (
                recordings?.length ? (
                    <ul className="overflow-y-auto border-t">
                        {recordings.map((rec, i) => (
                            <Fragment key={rec.id}>
                                {i > 0 && <div className="border-t" />}
                                <SessionRecordingPlaylistItem
                                    recording={rec}
                                    recordingProperties={{}}
                                    recordingPropertiesLoading={false}
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
                    <div className="p-4 text-muted-alt border-t border-dashed">{empty || info}</div>
                )
            ) : null}
        </div>
    )
}
