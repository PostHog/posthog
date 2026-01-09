import './PlayerUpNext.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlay } from '@posthog/icons'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerUpNext(): JSX.Element | null {
    const timeoutRef = useRef<any>()
    const { endReached, playNextAnimationInterrupted, playNextRecording } = useValues(sessionRecordingPlayerLogic)
    const { reportNextRecordingTriggered, setPlayNextAnimationInterrupted } = useActions(sessionRecordingPlayerLogic)
    const [animate, setAnimate] = useState(false)

    useKeyboardHotkeys(
        {
            n: {
                action: () => {
                    if (playNextRecording) {
                        reportNextRecordingTriggered(false)
                        playNextRecording(false)
                    }
                },
            },
        },
        [playNextRecording]
    )

    const goToRecording = (automatic: boolean): void => {
        if (!playNextRecording) {
            return
        }
        reportNextRecordingTriggered(automatic)
        playNextRecording(automatic)
    }

    useEffect(() => {
        clearTimeout(timeoutRef.current)

        if (endReached && playNextRecording) {
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
    }, [endReached, !!playNextRecording]) // oxlint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (playNextAnimationInterrupted) {
            clearTimeout(timeoutRef.current)
            setAnimate(false)
        }
    }, [playNextAnimationInterrupted])

    if (!playNextRecording) {
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
