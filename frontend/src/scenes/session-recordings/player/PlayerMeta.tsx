import './PlayerMeta.scss'
import React from 'react'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { useValues } from 'kea'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { TZLabel } from 'lib/components/TimezoneAware'
import { percentage, truncate } from 'lib/utils'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { SessionRecordingPlayerProps } from '~/types'
import clsx from 'clsx'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { Link } from '@posthog/lemon-ui'
import { playerSettingsLogic } from './playerSettingsLogic'

export function PlayerMetaV3({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const {
        sessionPerson,
        description,
        resolution,
        currentUrl,
        scale,
        currentWindowIndex,
        recordingStartTime,
        loading,
    } = useValues(playerMetaLogic({ sessionRecordingId, playerKey }))

    const { isFullScreen } = useValues(playerSettingsLogic)
    return (
        <div
            className={clsx('PlayerMetaV3', {
                'PlayerMetaV3--fullscreen': isFullScreen,
            })}
        >
            {isFullScreen && (
                <div className="PlayerMetaV3__escape">
                    <div className="bg-muted-dark text-white px-2 py-1 rounded shadow my-1 mx-auto">
                        Press <kbd className="font-bold">Esc</kbd> to exit full screen
                    </div>
                </div>
            )}

            <div
                className={clsx('flex items-center gap-2', {
                    'p-3 border-b': !isFullScreen,
                    'px-3 p-1 text-xs': isFullScreen,
                })}
            >
                <div className="mr-2">
                    {!sessionPerson ? (
                        <LemonSkeleton.Circle className="w-12 h-12" />
                    ) : (
                        <ProfilePicture
                            name={sessionPerson?.name}
                            email={sessionPerson?.properties?.$email}
                            size={!isFullScreen ? 'xxl' : 'md'}
                        />
                    )}
                </div>
                <div className="flex-1">
                    <div className="font-bold">
                        {!sessionPerson || !recordingStartTime ? (
                            <LemonSkeleton className="w-1/3 my-1" />
                        ) : (
                            <div className="flex gap-1">
                                <PersonHeader person={sessionPerson} withIcon={false} noEllipsis={true} />
                                {'·'}
                                <TZLabel
                                    time={dayjs(recordingStartTime)}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="h:mm A"
                                    showPopover={false}
                                />
                            </div>
                        )}
                    </div>
                    <div className=" text-muted">
                        {loading ? <LemonSkeleton className="w-1/4 my-1" /> : <span>{description}</span>}
                    </div>
                </div>
            </div>
            <div
                className={clsx('flex items-center justify-between gap-2 whitespace-nowrap', {
                    'p-3 h-12': !isFullScreen,
                    'p-1 px-3 text-xs': isFullScreen,
                })}
            >
                {loading || currentWindowIndex === -1 ? (
                    <LemonSkeleton className="w-1/3" />
                ) : (
                    <>
                        <IconWindow value={currentWindowIndex + 1} className="text-muted" />
                        <div className="window-number">Window {currentWindowIndex + 1}</div>
                        {currentUrl && (
                            <>
                                {'· '}
                                <Link to={currentUrl} target="_blank">
                                    {truncate(currentUrl, 32)}
                                </Link>
                                <span className="flex items-center">
                                    <CopyToClipboardInline description="current url" explicitValue={currentUrl} />
                                </span>
                            </>
                        )}
                    </>
                )}
                <div className="flex-1" />
                {loading ? (
                    <LemonSkeleton className="w-1/3" />
                ) : (
                    <span>
                        {resolution && (
                            <>
                                Resolution: {resolution.width} x {resolution.height} ({percentage(scale, 1, true)})
                            </>
                        )}
                    </span>
                )}
            </div>
        </div>
    )
}
