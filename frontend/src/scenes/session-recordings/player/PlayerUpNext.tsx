import './PlayerUpNext.scss'

import clsx from 'clsx'
import { BuiltLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlay } from '@posthog/icons'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

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

    useKeyboardHotkeys({
        n: {
            action: () => {
                if (nextSessionRecording?.id) {
                    reportNextRecordingTriggered(false)
                    setSelectedRecordingId(nextSessionRecording.id)
                }
            },
        },
    })

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
            timeoutRef.current = setTimeout(
                () => {
                    goToRecording(true)
                },
                // NOTE: Keep in sync with SCSS
                3000
            )
        }

        return () => clearTimeout(timeoutRef.current)
    }, [endReached, !!nextSessionRecording]) // oxlint-disable-line react-hooks/exhaustive-deps

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
        <Tooltip
            title={
                <>
                    Play the next recording <KeyboardShortcut n />
                </>
            }
        >
            <div className="PlayerUpNext text-xs">
                <div
                    className={clsx('px-1 py-0.5 PlayerUpNextButton', animate && 'PlayerUpNextButton--animating')}
                    onClick={() => goToRecording(false)}
                >
                    <div className="PlayerUpNextButtonBackground" />
                    <div className="z-10 flex items-center gap-1">
                        <IconPlay className="text-lg" /> Play next
                    </div>
                </div>
            </div>
        </Tooltip>
    )
}
