import './SessionRecordingsButton.scss'
import React, { ReactNode, useCallback, useState } from 'react'
import { PlayCircleOutlined, DownOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { SessionRecordingType } from '~/types'
import { colonDelimitedDuration, fromParams, humanFriendlyDetailedTime, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { Button } from 'antd'
import { Popup } from '../../lib/components/Popup/Popup'
import clsx from 'clsx'
import { Tooltip } from '../../lib/components/Tooltip'

interface SessionRecordingsButtonProps {
    sessionRecordings: SessionRecordingType[]
}

export const sessionPlayerUrl = (sessionRecordingId: string): string => {
    return `${location.pathname}?${toParams({ ...fromParams(), sessionRecordingId })}`
}

export function SessionRecordingsButton({ sessionRecordings }: SessionRecordingsButtonProps): JSX.Element {
    const [areRecordingsShown, setAreRecordingsShown] = useState(false)

    const wereAllRecordingsViewed = !sessionRecordings.some(({ viewed }) => !viewed)
    const isSingleRecording = sessionRecordings.length === 1

    /** A wrapper for the button, that handles differing behavior based on the number of recordings available:
     * When there's only one recording, hovering over the button shows the dropdown, and clicking opens the recording.
     * When there are more recordings, hovering over the button does nothing, and clicking shows the dropdown.
     */
    const ButtonWrapper: (props: {
        setRef: (ref: HTMLElement | null) => void
        children: ReactNode
    }) => JSX.Element = useCallback(
        ({ setRef, children }) => {
            return isSingleRecording ? (
                <div className="session-recordings-button__wrapper" ref={setRef}>
                    <Link
                        to={sessionPlayerUrl(sessionRecordings[0].id)}
                        onClick={(event) => {
                            event.stopPropagation()
                            setAreRecordingsShown(false)
                        }}
                        onMouseEnter={() => setAreRecordingsShown(true)}
                        onMouseLeave={() => setAreRecordingsShown(false)}
                    >
                        {children}
                    </Link>
                </div>
            ) : (
                <div
                    ref={setRef}
                    className="session-recordings-button__wrapper"
                    onClick={(event) => {
                        event.stopPropagation()
                        setAreRecordingsShown((previousValue) => !previousValue)
                    }}
                >
                    {children}
                </div>
            )
        },
        [sessionRecordings, setAreRecordingsShown]
    )

    return (
        <Popup
            visible={areRecordingsShown}
            placement="bottom-end"
            fallbackPlacements={['top-end']}
            className="session-recordings-popup"
            overlay={sessionRecordings.map(({ id, viewed, recording_duration, start_time }, index) => (
                <Link
                    key={id}
                    to={sessionPlayerUrl(id)}
                    className={clsx(
                        'session-recordings-popup__link',
                        viewed && 'session-recordings-popup__link--viewed'
                    )}
                    onClick={(event) => {
                        event.stopPropagation()
                        setAreRecordingsShown(false)
                    }}
                    data-attr="sessions-player-button"
                >
                    <div className="session-recordings-popup__row">
                        <div className="session-recordings-popup__label">
                            <Tooltip
                                title={
                                    viewed
                                        ? 'This recording has been watched already.'
                                        : 'This recording has not been watched yet.'
                                }
                            >
                                <PlayCircleOutlined className={viewed ? 'text-muted' : undefined} />
                            </Tooltip>
                            Recording {index + 1}
                        </div>
                        <div className="session-recordings-popup__detail text-muted">
                            {humanFriendlyDetailedTime(start_time)} • {colonDelimitedDuration(recording_duration)}
                        </div>
                    </div>
                </Link>
            ))}
            onClickOutside={() => {
                setAreRecordingsShown(false)
            }}
        >
            {({ setRef }) => (
                <ButtonWrapper setRef={setRef}>
                    <Button
                        className={clsx(
                            'session-recordings-button',
                            wereAllRecordingsViewed && 'session-recordings-button--all-viewed'
                        )}
                        data-attr="session-recordings-button"
                        icon={<PlayCircleOutlined />}
                    >
                        Watch session
                        {isSingleRecording ? (
                            <ArrowRightOutlined className="session-recordings-button__indicator" />
                        ) : (
                            <DownOutlined className="session-recordings-button__indicator" />
                        )}
                    </Button>
                </ButtonWrapper>
            )}
        </Popup>
    )
}
