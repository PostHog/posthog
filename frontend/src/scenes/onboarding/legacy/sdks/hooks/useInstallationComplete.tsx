import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

import { pollRecentAIEvents } from 'products/ai_observability/frontend/utils/aiEvents'

/**
 * Sentinel for `teamPropertyToVerify`: verify by polling for AI events instead of reading a
 * Team boolean — ingestion flips no team flag for AI events, so `ingested_event` would go
 * green on any event without any LLM instrumentation in place. If a second product ever
 * needs a custom check, replace the sentinel with a check-function prop.
 */
export const VERIFY_AI_EVENTS = '__ai_events__'

// Gentler than the 2s team-property poll: each miss can run a ClickHouse query.
const AI_EVENTS_POLL_MS = 5000

export const useInstallationComplete = (teamPropertyToVerify: string): boolean => {
    const { currentTeam } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)
    const [checking, setChecking] = useState(true)
    const [aiEventsSeen, setAiEventsSeen] = useState(false)
    const isAiEventsCheck = teamPropertyToVerify === VERIFY_AI_EVENTS
    const installationComplete = isAiEventsCheck
        ? aiEventsSeen
        : Boolean(currentTeam?.[teamPropertyToVerify as keyof TeamType])

    useInterval(
        () => {
            if (installationComplete) {
                return
            }
            if (isAiEventsCheck) {
                if (currentTeam?.id) {
                    void pollRecentAIEvents(currentTeam.id).then((seen) => seen && setAiEventsSeen(true))
                }
            } else {
                loadCurrentTeam()
            }
        },
        isAiEventsCheck ? AI_EVENTS_POLL_MS : 2000
    )

    // The interval first fires after its delay; check right away so a user who already has AI
    // events isn't shown "waiting" for the first tick.
    useEffect(() => {
        if (isAiEventsCheck && !aiEventsSeen && currentTeam?.id) {
            void pollRecentAIEvents(currentTeam.id).then((seen) => seen && setAiEventsSeen(true))
        }
    }, [isAiEventsCheck, aiEventsSeen, currentTeam?.id])

    useEffect(() => {
        if (checking && !installationComplete) {
            setTimeout(() => setChecking(false), 5000)
        }
    }, [checking, installationComplete])

    return installationComplete
}
