import './PlayerMeta.scss'
import React from 'react'
import { Col, Row, Skeleton, Space } from 'antd'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { useValues } from 'kea'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import { TZLabel } from 'lib/components/TimezoneAware'
import { percentage, truncate } from 'lib/utils'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { SessionRecordingPlayerProps } from '~/types'
import clsx from 'clsx'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { Link } from '@posthog/lemon-ui'

export function PlayerMetaV2({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { sessionPerson, description, resolution, scale, recordingStartTime, loading } = useValues(
        metaLogic({ sessionRecordingId, playerKey })
    )

    return (
        <Col className="player-meta-container-v2">
            <Row className="player-meta-person" align="middle" justify="space-between" wrap={false}>
                <Row className="player-meta-person-title" align="middle" wrap={false}>
                    {loading ? (
                        <Space>
                            <Skeleton.Avatar active size="small" shape="circle" />
                            <Skeleton title={false} active paragraph={{ rows: 1, width: 160 }} />
                        </Space>
                    ) : (
                        <>
                            <ProfilePicture
                                name={sessionPerson?.name}
                                email={sessionPerson?.properties?.$email}
                                size="md"
                                style={{ marginRight: '0.5rem' }}
                            />
                            <span className="email">
                                <PersonHeader person={sessionPerson} withIcon={false} />
                            </span>
                        </>
                    )}
                </Row>
                <Col>
                    {loading ? (
                        <Skeleton title={false} active paragraph={{ rows: 1, width: 80 }} />
                    ) : (
                        <span className="time text-muted">
                            {recordingStartTime && <TZLabel time={dayjs(recordingStartTime)} />}
                        </span>
                    )}
                </Col>
            </Row>
            <Row className="player-meta-other" align="middle" justify="start">
                <Row className="player-meta-other-description">
                    {loading ? <Skeleton title={false} active paragraph={{ rows: 1 }} /> : <span>{description}</span>}
                </Row>
                <Row className="player-meta-other-resolution mt-2">
                    {loading ? (
                        <Skeleton title={false} active paragraph={{ rows: 1, width: '100%' }} />
                    ) : (
                        <span>
                            {resolution ? (
                                <>
                                    Resolution: {resolution.width} x {resolution.height} ({percentage(scale, 1, true)})
                                </>
                            ) : (
                                <>Resolution: ...</>
                            )}
                        </span>
                    )}
                </Row>
            </Row>
        </Col>
    )
}

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
        isFullScreen,
    } = useValues(metaLogic({ sessionRecordingId, playerKey }))
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
                        <IconWindow
                            value={currentWindowIndex + 1}
                            className="text-muted"
                            style={{ marginRight: '0.25rem' }}
                        />
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
