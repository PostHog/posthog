import { useEffect, useState } from 'react'

import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

const PLAYER_MOUNT_WAIT_FRAMES = 20

export type PlayerMountState = 'mounted' | 'waiting' | 'missing'

/**
 * The player logic is keyed, and the list column renders before the player in the same commit, so the first frame
 * after a recording changes can find no instance yet. Building one from the list would start a second player, so wait
 * a few frames instead, and give up when a host renders the list without a player at all.
 */
export function usePlayerMounted(playerLogicProps: SessionRecordingPlayerLogicProps): PlayerMountState {
    const [attempts, setAttempts] = useState(0)
    const mounted = !!sessionRecordingPlayerLogic.findMounted(playerLogicProps)
    useEffect(() => {
        if (mounted || attempts >= PLAYER_MOUNT_WAIT_FRAMES) {
            return
        }
        const frame = requestAnimationFrame(() => setAttempts((n) => n + 1))
        return () => cancelAnimationFrame(frame)
    }, [mounted, attempts])
    return mounted ? 'mounted' : attempts >= PLAYER_MOUNT_WAIT_FRAMES ? 'missing' : 'waiting'
}
