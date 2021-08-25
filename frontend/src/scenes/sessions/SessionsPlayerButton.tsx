import './SessionsPlayerButton.scss'
import React, { useState } from 'react'
import { PlayCircleOutlined, CaretDownOutlined } from '@ant-design/icons'
import { SessionRecordingType } from '~/types'
import { colonDelimitedDuration, fromParams, humanFriendlyDetailedTime, toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { Button } from 'antd'
import { Popup } from '../../lib/components/Popup/Popup'

interface SessionsPlayerButtonProps {
    sessionRecordings: SessionRecordingType[]
}

export const sessionPlayerUrl = (sessionRecordingId: string): string => {
    return `${location.pathname}?${toParams({ ...fromParams(), sessionRecordingId })}`
}

export function SessionsPlayerButton({ sessionRecordings }: SessionsPlayerButtonProps): JSX.Element {
    const [areRecordingsShown, setAreRecordingsShown] = useState(false)

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
                    className={`session-recordings-popup__link${
                        viewed ? ' session-recordings-popup__link--viewed' : ''
                    }`}
                    onClick={(event) => {
                        event.stopPropagation()
                        setAreRecordingsShown(false)
                    }}
                >
                    <div className="session-recordings-popup__row">
                        <div className="session-recordings-popup__label">
                            <PlayCircleOutlined />
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
            <Button
                className="session-recordings-button"
                onClick={(event) => {
                    event.stopPropagation()
                    setAreRecordingsShown((previousValue) => !previousValue)
                }}
            >
                Watch session
                <CaretDownOutlined
                    className={`session-recordings-button__indicator ${
                        areRecordingsShown
                            ? 'session-recordings-button__indicator--open'
                            : 'session-recordings-button__indicator--closed'
                    }`}
                />
            </Button>
        </Popup>
    )
}
