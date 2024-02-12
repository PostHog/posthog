import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import type { autocaptureExceptionsLogicType } from './autocaptureExceptionsLogicType'

export const autocaptureExceptionsLogic = kea<autocaptureExceptionsLogicType>([
    path(['scenes', 'project', 'Settings', 'autocaptureExceptionsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions({
        setErrorsToIgnoreRules: (newRules: string) => ({ newRules }),
    }),
    reducers({
        errorsToIgnoreRules: [
            '',
            {
                setErrorsToIgnoreRules: (_, { newRules }) => newRules,
            },
        ],
    }),
    selectors({
        currentTeamErrorsToIgnoreRules: [
            (s) => [s.currentTeam],
            (currentTeam) => (currentTeam?.autocapture_exceptions_errors_to_ignore || []).join('\n'),
        ],
        rulesCharacters: [(s) => [s.errorsToIgnoreRules], (errorsToIgnoreRules) => errorsToIgnoreRules.length],
    }),
    listeners(({ actions, values }) => ({
        setErrorsToIgnoreRules: async ({ newRules }, breakpoint) => {
            if (values.currentTeamErrorsToIgnoreRules === newRules.trim()) {
                return
            }

            await breakpoint(300)

            const updateRules = newRules
                .trim()
                .split('\n')
                .map((rule) => rule.trim())
                .filter((rule) => !!rule)
            actions.updateCurrentTeam({
                autocapture_exceptions_errors_to_ignore: updateRules,
            })
        },
    })),
    afterMount(({ actions, values }) => {
        actions.setErrorsToIgnoreRules(values.currentTeamErrorsToIgnoreRules)
    }),
])
