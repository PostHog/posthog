import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

import { onboardingEventUsageLogic } from '../../../onboardingEventUsageLogic'

export const useInstallationComplete = (teamPropertyToVerify: string): boolean => {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const { reportOnboardingInstallationVerified } = useActions(onboardingEventUsageLogic)
    const [checking, setChecking] = useState(true)
    const installationComplete = Boolean(currentTeam?.[teamPropertyToVerify as keyof TeamType])

    // Whether the property was already set when the team first loaded — distinguishes a live
    // verification ('transition') from re-entering onboarding after the fact ('already_complete').
    const initialCompleteRef = useRef<boolean | null>(null)
    if (initialCompleteRef.current === null && currentTeam) {
        initialCompleteRef.current = installationComplete
    }

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

    // Concurrent mounts (step, instructions modal, indicator) all report; the logic's listener
    // dedupes to one `onboarding installation verified` per pageload.
    useEffect(() => {
        if (installationComplete && initialCompleteRef.current !== null) {
            reportOnboardingInstallationVerified(
                initialCompleteRef.current ? 'already_complete' : 'transition',
                teamPropertyToVerify
            )
        }
    }, [installationComplete, reportOnboardingInstallationVerified, teamPropertyToVerify])

    return installationComplete
}
