import './KioskPlayer.scss'

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'

import { useEventListener } from 'lib/hooks/useEventListener'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from '../player/sessionRecordingPlayerLogic'
import { sessionRecordingsKioskLogic } from './sessionRecordingsKioskLogic'

const INACTIVITY_TIMEOUT_MS = 3000

export function KioskPlayer(): JSX.Element | null {
    const { currentRecordingId, currentRecording } = useValues(sessionRecordingsKioskLogic)
    const { advanceToNextRecording } = useActions(sessionRecordingsKioskLogic)
    const [isActive, setIsActive] = useState(false)
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const handleActivity = useCallback((): void => {
        setIsActive(true)

        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current)
        }

        timeoutRef.current = setTimeout(() => {
            setIsActive(false)
        }, INACTIVITY_TIMEOUT_MS)
    }, [])

    useEventListener('mousemove', handleActivity)
    useEventListener('mousedown', handleActivity)

    useEffect(() => {
        return () => {
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
        }
    }, [])

    const handleClose = (): void => {
        router.actions.push(urls.replay())
    }

    const playerKey = `kiosk-player-${currentRecordingId}`

    if (!currentRecordingId || !currentRecording) {
        return (
            <div className="KioskPlayer KioskPlayer--loading">
                <div className="KioskPlayer__message">Loading recordings...</div>
            </div>
        )
    }

    return (
        <div className="KioskPlayer">
            <SessionRecordingPlayer
                playerKey={playerKey}
                sessionRecordingId={currentRecordingId}
                mode={SessionRecordingPlayerMode.Kiosk}
                autoPlay={true}
                withSidebar={false}
                noMeta={true}
                noBorder={true}
                playNextRecording={() => advanceToNextRecording()}
            />
            <div
                className={`absolute inset-0 z-10 transition-opacity duration-300 ${
                    isActive ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
                }`}
            >
                <LemonButton
                    type="secondary"
                    icon={<IconX className="text-2xl" />}
                    size="large"
                    onClick={handleClose}
                    className="absolute top-6 right-6 !bg-white !text-black hover:!bg-gray-200"
                    tooltip="Exit kiosk mode"
                />
            </div>
        </div>
    )
}
