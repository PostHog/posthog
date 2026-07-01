import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

export const useInstallationComplete = (teamPropertyToVerify: string): boolean => {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const installationComplete = Boolean(currentTeam?.[teamPropertyToVerify as keyof TeamType])

    useInterval(() => {
        if (!installationComplete) {
            loadCurrentTeam()
        }
    }, 2000)

    return installationComplete
}

/**
 * Returns true once verification has been waiting `delayMs` without completing.
 * Drives the install step's escape hatch — enabling Continue and showing a hint —
 * so users aren't trapped on a "Waiting for…" indicator that may never resolve for
 * their setup (e.g. events blocked, or a flow where no event ever lands).
 */
export const useVerificationStalled = (installationComplete: boolean, delayMs = 30000): boolean => {
    const [stalled, setStalled] = useState(false)

    useEffect(() => {
        if (installationComplete) {
            setStalled(false)
            return
        }
        const timeout = setTimeout(() => setStalled(true), delayMs)
        return () => clearTimeout(timeout)
    }, [installationComplete, delayMs])

    return stalled
}
