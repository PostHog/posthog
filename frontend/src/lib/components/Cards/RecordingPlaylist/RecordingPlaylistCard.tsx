import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/Cards/handles'
import clsx from 'clsx'
import { DashboardTile, DashboardType, SessionRecordingPlaylistType } from '~/types'
import { LemonButton, LemonButtonWithPopup, LemonDivider } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dashboardsModel } from '~/models/dashboardsModel'
import React, { useState } from 'react'
import { CardMeta, Resizeable } from 'lib/components/Cards/Card'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'

interface RecordingPlaylistCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    dashboardId?: string | number
    playlistTile: DashboardTile
    children?: JSX.Element
    removeFromDashboard?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
}

interface RecordingPlaylistCardBodyProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'style'> {
    playlist: SessionRecordingPlaylistType
    closeDetails?: () => void
}

export function RecordingPlaylistCardBody({
    playlist,
    closeDetails,
    style,
}: RecordingPlaylistCardBodyProps): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="RecordingPlaylistCard-Body w-full" onClick={() => closeDetails?.()} style={style}>
            <SessionRecordingsPlaylist
                playlistShortId={playlist.short_id}
                filters={playlist.filters}
                showPlayer={false}
            />
        </div>
    )
}

export function RecordingPlaylistCardInternal(
    {
        playlistTile,
        showResizeHandles,
        canResizeWidth,
        children,
        className,
        dashboardId,
        moreButtons,
        removeFromDashboard,
        duplicate,
        moveToDashboard,
        showEditingControls = true,
        ...divProps
    }: RecordingPlaylistCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    // const { push } = useActions(router)

    const [metaPrimaryHeight, setMetaPrimaryHeight] = useState<number | undefined>(undefined)
    const [areDetailsShown, setAreDetailsShown] = useState(false)

    if (!playlistTile.recording_playlist) {
        throw new Error('RecordingPlaylistCard requires a playlist')
    }

    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards = nameSortedDashboards.filter((dashboard) => dashboard.id !== dashboardId)
    return (
        <div
            className={clsx('RecordingPlaylistCard rounded flex flex-col', className, showResizeHandles && 'border')}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            <CardMeta
                showEditingControls={showEditingControls}
                showDetailsControls={true}
                setAreDetailsShown={setAreDetailsShown}
                areDetailsShown={areDetailsShown}
                className={clsx(showResizeHandles ? 'border-b' : 'border rounded-t')}
                metaDetails={
                    <UserActivityIndicator
                        className={'mt-1'}
                        at={playlistTile.recording_playlist.last_modified_at}
                        by={
                            playlistTile.recording_playlist.created_by ||
                            playlistTile.recording_playlist.last_modified_by
                        }
                    />
                }
                moreButtons={
                    <>
                        {/*<LemonButton*/}
                        {/*    status="stealth"*/}
                        {/*    fullWidth*/}
                        {/*    onClick={() => dashboardId && push(urls.dashboardTextTile(dashboardId, textTile.id))}*/}
                        {/*    data-attr="edit-text"*/}
                        {/*>*/}
                        {/*    Edit text*/}
                        {/*</LemonButton>*/}

                        {moveToDashboard && otherDashboards.length > 0 && (
                            <LemonButtonWithPopup
                                status="stealth"
                                popup={{
                                    overlay: otherDashboards.map((otherDashboard) => (
                                        <LemonButton
                                            key={otherDashboard.id}
                                            status="stealth"
                                            onClick={() => {
                                                moveToDashboard(otherDashboard)
                                            }}
                                            fullWidth
                                        >
                                            {otherDashboard.name || <i>Untitled</i>}
                                        </LemonButton>
                                    )),
                                    placement: 'right-start',
                                    fallbackPlacements: ['left-start'],
                                    actionable: true,
                                    closeParentPopupOnClickInside: true,
                                }}
                                fullWidth
                            >
                                Move to
                            </LemonButtonWithPopup>
                        )}
                        <LemonButton
                            status="stealth"
                            onClick={duplicate}
                            fullWidth
                            data-attr={'duplicate-text-from-dashboard'}
                        >
                            Duplicate
                        </LemonButton>
                        {moreButtons && (
                            <>
                                <LemonDivider />
                                {moreButtons}
                            </>
                        )}
                        <LemonDivider />
                        {removeFromDashboard && (
                            <LemonButton
                                status="danger"
                                onClick={removeFromDashboard}
                                fullWidth
                                data-attr="remove-text-tile-from-dashboard"
                            >
                                Remove from dashboard
                            </LemonButton>
                        )}
                    </>
                }
                setPrimaryHeight={setMetaPrimaryHeight}
            />

            <RecordingPlaylistCardBody
                playlist={playlistTile.recording_playlist}
                closeDetails={() => setAreDetailsShown(false)}
                style={
                    metaPrimaryHeight
                        ? { height: `calc(100% - ${metaPrimaryHeight}px - 2rem /* margins */ - 1px /* border */)` }
                        : undefined
                }
            />

            {showResizeHandles && (
                <>
                    {canResizeWidth ? <ResizeHandle1D orientation="vertical" /> : null}
                    <ResizeHandle1D orientation="horizontal" />
                    {canResizeWidth ? <ResizeHandle2D /> : null}
                </>
            )}
            {children /* Extras, such as resize handles */}
        </div>
    )
}

export const RecordingPlaylistCard = React.forwardRef(
    RecordingPlaylistCardInternal
) as typeof RecordingPlaylistCardInternal
