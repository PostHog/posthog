import { kea, reducers, actions, listeners, events, selectors, connect, path } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import type { autocaptureExceptionsLogicType } from './autocaptureExceptionsLogicType'

export const autocaptureExceptionsLogic = kea<autocaptureExceptionsLogicType>([
    path(['scenes', 'project', 'Settings', 'autocaptureExceptionsLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        setErrorsToDropRules: (newRules: string) => ({ newRules }),
    }),
    reducers({
        errorsToDropRules: [
            (teamLogic.values.currentTeam?.autocapture_exceptions_errors_to_drop || []).join('\n'),
            {
                setErrorsToDropRules: (_, { newRules }) => newRules,
            },
        ],
        rulesCharacters: [
            0,
            {
                setErrorsToDropRules: (_, { newRules }) => newRules.length,
            },
        ],
    }),
    selectors({
        currentTeamErrorsToDropRules: [
            (s) => [s.currentTeam],
            (currentTeam) => (currentTeam?.autocapture_exceptions_errors_to_drop || []).join('\n'),
        ],
    }),
    listeners(({ actions, values }) => ({
        setErrorsToDropRules: async ({ newRules }, breakpoint) => {
            if (values.currentTeamErrorsToDropRules === newRules.trim()) {
                return
            }

            await breakpoint(300)

            const updateRules = newRules
                .trim()
                .split('\n')
                .map((rule) => rule.trim())
                .filter((rule) => !!rule)
            actions.updateCurrentTeam({
                autocapture_exceptions_errors_to_drop: updateRules,
            })
        },
    })),
    events(() => ({})),
])
