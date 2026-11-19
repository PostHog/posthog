import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

import { pollRecentAIEvents } from 'products/ai_observability/frontend/utils/aiEvents'

/**
 * Sentinel for `teamPropertyToVerify`: poll for AI events instead of reading a Team boolean,
 * because ingestion flips no team flag for AI events (`ingested_event` goes green on any event).
 */
export const VERIFY_AI_EVENTS = '__ai_events__'

// Gentler than the 2s team-property poll because each miss can run a ClickHouse query.
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
                    void pollRecentAIEvents().then((seen) => seen && setAiEventsSeen(true))
                }
            } else {
                loadCurrentTeam()
            }
        },
        isAiEventsCheck ? AI_EVENTS_POLL_MS : 2000
    )

    // Immediate check so a returning user isn't stuck waiting for the first interval tick.
    useEffect(() => {
        if (isAiEventsCheck && !aiEventsSeen && currentTeam?.id) {
            void pollRecentAIEvents().then((seen) => seen && setAiEventsSeen(true))
        }
    }, [isAiEventsCheck, aiEventsSeen, currentTeam?.id])

    useEffect(() => {
        if (checking && !installationComplete) {
            setTimeout(() => setChecking(false), 5000)
        }
    }, [checking, installationComplete])

    return installationComplete
}
