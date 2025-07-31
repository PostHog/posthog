import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

export const useInstallationComplete = (teamPropertyToVerify: string): boolean => {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const [checking, setChecking] = useState(true)
    const installationComplete = Boolean(currentTeam?.[teamPropertyToVerify as keyof TeamType])

    useInterval(() => {
        if (!installationComplete) {
            loadCurrentTeam()
        }
    }, 2000)

    useEffect(() => {
        if (checking && !installationComplete) {
            setTimeout(() => setChecking(false), 5000)
        }
    }, [checking, installationComplete])

    return installationComplete
}
