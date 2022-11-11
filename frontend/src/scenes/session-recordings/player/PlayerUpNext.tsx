import './PlayerUpNext.scss'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from './sessionRecordingPlayerLogic'
import { SessionRecordingType } from '~/types'
import { CSSTransition } from 'react-transition-group'
import { useActions, useValues } from 'kea'
import { IconPlay } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { router } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { playerSettingsLogic } from './playerSettingsLogic'

export interface PlayerUpNextProps extends SessionRecordingPlayerLogicProps {
    nextSessionRecording?: Partial<SessionRecordingType>
}

export function PlayerUpNext({
    sessionRecordingId,
    playerKey,
    nextSessionRecording,
}: PlayerUpNextProps): JSX.Element | null {
    const timeoutRef = useRef<any>()
    const { endReached } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { reportNextRecordingTriggered } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const [animate, setAnimate] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)
    const { autoplayEnabled } = useValues(playerSettingsLogic)

    if (!autoplayEnabled || !featureFlags[FEATURE_FLAGS.RECORDING_AUTOPLAY]) {
        nextSessionRecording = undefined
    }

    const goToRecording = (automatic: boolean): void => {
        reportNextRecordingTriggered(automatic)
        router.actions.push(router.values.currentLocation.pathname, router.values.currentLocation.searchParams, {
            sessionRecordingId: nextSessionRecording?.id,
        })
    }

    useEffect(() => {
        clearTimeout(timeoutRef.current)

        if (endReached && nextSessionRecording) {
            setAnimate(true)
            timeoutRef.current = setTimeout(() => {
                goToRecording(true)
            }, 3000) // NOTE: Keep in sync with SCSS
        }

        return () => clearTimeout(timeoutRef.current)
    }, [endReached, !!nextSessionRecording])

    const onHover = (): void => {
        clearTimeout(timeoutRef.current)
        setAnimate(false)
    }

    if (!nextSessionRecording) {
        return null
    }

    return (
        <CSSTransition in={endReached} timeout={250} classNames="PlayerUpNext-" mountOnEnter unmountOnExit>
            <Tooltip title={'Play the next recording (press enter)'}>
                <div className="PlayerUpNext">
                    <div
                        className={clsx('PlayerUpNextButton', animate && 'PlayerUpNextButton--animating')}
                        onMouseMove={() => onHover()}
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
