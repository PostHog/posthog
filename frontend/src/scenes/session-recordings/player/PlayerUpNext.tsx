import './PlayerUpNext.scss'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { CSSTransition } from 'react-transition-group'
import { useActions, useValues } from 'kea'
import { IconPlay } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { router } from 'kea-router'

export interface PlayerUpNextProps {
    interrupted?: boolean
    clearInterrupted?: () => void
}

export function PlayerUpNext({ interrupted, clearInterrupted }: PlayerUpNextProps): JSX.Element | null {
    const timeoutRef = useRef<any>()
    const { endReached, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { reportNextRecordingTriggered } = useActions(sessionRecordingPlayerLogic)
    const [animate, setAnimate] = useState(false)

    const nextSessionRecording = logicProps.nextSessionRecording

    const goToRecording = (automatic: boolean): void => {
        reportNextRecordingTriggered(automatic)
        router.actions.push(
            router.values.currentLocation.pathname,
            {
                ...router.values.currentLocation.searchParams,
                sessionRecordingId: nextSessionRecording?.id,
            },
            router.values.currentLocation.hashParams
        )
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
