import { actions, afterMount, kea, listeners, path, reducers } from 'kea'

import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import type { maxWebAnalyticsNudgeSessionLogicType } from './maxWebAnalyticsNudgeSessionLogicType'

const STORAGE_KEY = 'posthog-ai-web-analytics-nudge-session'

export interface NudgeSessionState {
    shownForMessageId: string | null
    dismissed: boolean
    eligibleReported: boolean
}

const EMPTY_STATE: NudgeSessionState = {
    shownForMessageId: null,
    dismissed: false,
    eligibleReported: false,
}

function readState(): NudgeSessionState {
    try {
        const raw = window.sessionStorage.getItem(STORAGE_KEY)
        if (!raw) {
            return EMPTY_STATE
        }
        return { ...EMPTY_STATE, ...(JSON.parse(raw) as Partial<NudgeSessionState>) }
    } catch {
        return EMPTY_STATE
    }
}

function writeState(state: NudgeSessionState): void {
    try {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
        return
    }
}

export const maxWebAnalyticsNudgeSessionLogic = kea<maxWebAnalyticsNudgeSessionLogicType>([
    path(['scenes', 'max', 'logics', 'maxWebAnalyticsNudgeSessionLogic']),

    actions({
        markNudgeShown: (messageId: string) => ({ messageId }),
        markNudgeDismissed: true,
        markEligibleReported: true,
        hydrateFromStorage: (state: NudgeSessionState) => ({ state }),
    }),

    reducers({
        shownForMessageId: [
            null as string | null,
            {
                markNudgeShown: (_, { messageId }) => messageId,
                hydrateFromStorage: (_, { state }) => state.shownForMessageId,
            },
        ],
        dismissedThisSession: [
            false,
            {
                markNudgeDismissed: () => true,
                hydrateFromStorage: (_, { state }) => state.dismissed,
            },
        ],
        eligibleReportedThisSession: [
            false,
            {
                markEligibleReported: () => true,
                hydrateFromStorage: (_, { state }) => state.eligibleReported,
            },
        ],
    }),

    listeners(({ values }) => {
        const persist = (): void => {
            writeState({
                shownForMessageId: values.shownForMessageId,
                dismissed: values.dismissedThisSession,
                eligibleReported: values.eligibleReportedThisSession,
            })
        }
        return {
            markNudgeShown: persist,
            markNudgeDismissed: persist,
            markEligibleReported: persist,
        }
    }),

    afterMount(({ actions }) => {
        actions.hydrateFromStorage(readState())
    }),

    permanentlyMount(),
])
