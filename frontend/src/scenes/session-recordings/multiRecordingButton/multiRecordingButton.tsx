import React, { MutableRefObject, ReactNode, useCallback, useState } from 'react'
import { PlayCircleOutlined, DownOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { MatchedRecording } from '~/types'
import { Button } from 'antd'
import { Popup } from '../../../lib/components/Popup/Popup'
import { Link } from 'lib/components/Link'
import './multiRecordingButton.scss'

interface MultiRecordingButtonProps {
    sessionRecordings: MatchedRecording[]
    onOpenRecording: (sessionRecording: MatchedRecording) => void
}

export function MultiRecordingButton({ sessionRecordings, onOpenRecording }: MultiRecordingButtonProps): JSX.Element {
    const [areRecordingsShown, setAreRecordingsShown] = useState(false)

    const isSingleRecording = sessionRecordings.length === 1

    /** A wrapper for the button, that handles differing behavior based on the number of recordings available:
     * When there's only one recording, clicking opens the recording.
     * When there are more recordings, clicking shows the dropdown.
     */
    const ButtonWrapper: (props: { ref: MutableRefObject<HTMLElement | null>; children: ReactNode }) => JSX.Element =
        useCallback(
            ({ ref, children }) => {
                return isSingleRecording ? (
                    <div ref={ref as MutableRefObject<HTMLDivElement>}>
                        <Link
                            onClick={(event) => {
                                event.stopPropagation()
                                onOpenRecording(sessionRecordings[0])
                            }}
                        >
                            {children}
                        </Link>
                    </div>
                ) : (
                    <div
                        ref={ref as MutableRefObject<HTMLDivElement>}
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
            overlay={sessionRecordings.map((sessionRecording, index) => (
                <Link
                    key={sessionRecording.session_id}
                    onClick={(event) => {
                        event.stopPropagation()
                        setAreRecordingsShown(false)
                        onOpenRecording(sessionRecording)
                    }}
                >
                    <div className="session-recordings-popup-row">
                        <PlayCircleOutlined />
                        Recording {index + 1}
                    </div>
                </Link>
            ))}
            onClickOutside={() => {
                setAreRecordingsShown(false)
            }}
        >
            {({ ref }) => (
                <ButtonWrapper ref={ref}>
                    <Button
                        className={'session-recordings-button'}
                        data-attr="session-recordings-button"
                        icon={<PlayCircleOutlined />}
                    >
                        Watch recording
                        {isSingleRecording ? <ArrowRightOutlined /> : <DownOutlined />}
                    </Button>
                </ButtonWrapper>
            )}
        </Popup>
    )
}
