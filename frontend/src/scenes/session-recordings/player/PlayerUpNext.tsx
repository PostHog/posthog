import './PlayerUpNext.scss'

import { IconPlay } from '@posthog/icons'
import clsx from 'clsx'
import { BuiltLogic, useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect, useRef, useState } from 'react'

import { sessionRecordingsPlaylistLogicType } from '../playlist/sessionRecordingsPlaylistLogicType'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export interface PlayerUpNextProps {
    playlistLogic: BuiltLogic<sessionRecordingsPlaylistLogicType>
}

export function PlayerUpNext({ playlistLogic }: PlayerUpNextProps): JSX.Element | null {
    const timeoutRef = useRef<any>()
    const { endReached, playNextAnimationInterrupted } = useValues(sessionRecordingPlayerLogic)
    const { reportNextRecordingTriggered, setPlayNextAnimationInterrupted } = useActions(sessionRecordingPlayerLogic)
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
            setPlayNextAnimationInterrupted(false)
            timeoutRef.current = setTimeout(() => {
                goToRecording(true)
            }, 3000) // NOTE: Keep in sync with SCSS
        }

        return () => clearTimeout(timeoutRef.current)
    }, [endReached, !!nextSessionRecording])

    useEffect(() => {
        if (playNextAnimationInterrupted) {
            clearTimeout(timeoutRef.current)
            setAnimate(false)
        }
    }, [playNextAnimationInterrupted])

    if (!nextSessionRecording) {
        return null
    }

    return (
        <Tooltip title="Play the next recording (press enter)">
            <div className="PlayerUpNext text-xs">
                <div
                    className={clsx('px-1 py-0.5 PlayerUpNextButton', animate && 'PlayerUpNextButton--animating')}
                    onClick={() => goToRecording(false)}
                >
                    <div className="w-full PlayerUpNextButtonBackground" />
                    <div className="z-10 flex items-center gap-2">
                        <IconPlay className="text-lg" /> Play next
                    </div>
                </div>
            </div>
        </Tooltip>
    )
}
