import './PlayerUpNext.scss'

import { IconPlay } from '@posthog/icons'
import clsx from 'clsx'
import { BuiltLogic, useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect, useRef, useState } from 'react'
import { CSSTransition } from 'react-transition-group'

import { sessionRecordingsPlaylistLogicType } from '../playlist/sessionRecordingsPlaylistLogicType'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export interface PlayerUpNextProps {
    playlistLogic: BuiltLogic<sessionRecordingsPlaylistLogicType>
    interrupted?: boolean
    clearInterrupted?: () => void
}

export function PlayerUpNext({ interrupted, clearInterrupted, playlistLogic }: PlayerUpNextProps): JSX.Element | null {
    const timeoutRef = useRef<any>()
    const { endReached } = useValues(sessionRecordingPlayerLogic)
    const { reportNextRecordingTriggered } = useActions(sessionRecordingPlayerLogic)
    const [animate, setAnimate] = useState(false)

    const { nextSessionRecording } = useValues(playlistLogic)
    const { setSelectedRecordingId } = useActions(playlistLogic)

    const goToRecording = (automatic: boolean): void => {
        if (!nextSessionRecording?.id) {
            return
        }
        reportNextRecordingTriggered(automatic)
        setSelectedRecordingId(nextSessionRecording.id)
    }

    useEffect(() => {
        clearTimeout(timeoutRef.current)

        if (endReached && nextSessionRecording?.id) {
            setAnimate(true)
            clearInterrupted?.()
            timeoutRef.current = setTimeout(() => {
                goToRecording(true)
            }, 3000) // NOTE: Keep in sync with SCSS
        }

        return () => clearTimeout(timeoutRef.current)
    }, [endReached, !!nextSessionRecording])

    useEffect(() => {
        if (interrupted) {
            clearTimeout(timeoutRef.current)
            setAnimate(false)
        }
    }, [interrupted])

    if (!nextSessionRecording) {
        return null
    }

    return (
        <CSSTransition in={endReached} timeout={250} classNames="PlayerUpNext-" mountOnEnter unmountOnExit>
            <Tooltip title="Play the next recording (press enter)">
                <div className="PlayerUpNext">
                    <div
                        className={clsx('PlayerUpNextButton', animate && 'PlayerUpNextButton--animating')}
                        onClick={() => goToRecording(false)}
                    >
                        <div className="PlayerUpNextButtonBackground" />
                        <div className="z-10 flex items-center gap-2">
                            <IconPlay className="text-lg" /> Next recording
                        </div>
                    </div>
                </div>
            </Tooltip>
        </CSSTransition>
    )
}
