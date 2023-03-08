import './PlayerUpNext.scss'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from './sessionRecordingPlayerLogic'
import { SessionRecordingType } from '~/types'
import { CSSTransition } from 'react-transition-group'
import { useActions, useValues } from 'kea'
import { IconPlay } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { router } from 'kea-router'
import { playerSettingsLogic } from './playerSettingsLogic'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'

export interface PlayerUpNextProps extends SessionRecordingPlayerLogicProps {
    nextSessionRecording?: Partial<SessionRecordingType>
    interrupted?: boolean
    clearInterrupted?: () => void
}

export function PlayerUpNext({
    sessionRecordingId,
    playerKey,
    nextSessionRecording,
    interrupted,
    clearInterrupted,
}: PlayerUpNextProps): JSX.Element | null {
    const timeoutRef = useRef<any>()
    const unmountNextRecordingDataLogicRef = useRef<() => void>()
    const { endReached } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { reportNextRecordingTriggered } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const [animate, setAnimate] = useState(false)
    const { autoplayEnabled } = useValues(playerSettingsLogic)

    if (!autoplayEnabled) {
        nextSessionRecording = undefined
    }

    const goToRecording = (automatic: boolean): void => {
        reportNextRecordingTriggered(automatic)
        router.actions.push(router.values.currentLocation.pathname, router.values.currentLocation.searchParams, {
            ...router.values.currentLocation.hashParams,
            sessionRecordingId: nextSessionRecording?.id,
        })
    }

    useEffect(() => {
        clearTimeout(timeoutRef.current)

        if (endReached && nextSessionRecording?.id) {
            if (!unmountNextRecordingDataLogicRef.current) {
                // Small optimisation - preload the next recording session data
                unmountNextRecordingDataLogicRef.current = sessionRecordingDataLogic({
                    sessionRecordingId: nextSessionRecording.id,
                }).mount()
            }

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

    useEffect(() => {
        // If we have a mounted logic for preloading, unmount it
        return () => {
            const unmount = unmountNextRecordingDataLogicRef.current
            unmountNextRecordingDataLogicRef.current = undefined
            setTimeout(() => {
                unmount?.()
            }, 3000)
        }
    }, [nextSessionRecording?.id])

    if (!nextSessionRecording) {
        return null
    }

    return (
        <CSSTransition in={endReached} timeout={250} classNames="PlayerUpNext-" mountOnEnter unmountOnExit>
            <Tooltip title={'Play the next recording (press enter)'}>
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
