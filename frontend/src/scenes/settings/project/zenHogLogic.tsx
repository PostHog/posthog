import { kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { capitalizeFirstLetter } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import type { zenHogLogicType } from './zenHogLogicType'

export const zenHogLogic = kea<zenHogLogicType>([
    path(['scenes', 'project', 'Settings', 'ZenHogLogic']),
    loaders(() => ({
        testedZendeskKey: [
            null as string | null,
            {
                testZendeskKey: async (zendeskKey: string) => {
                    // TODO: add some kind of verification that it's a valid key
                    return zendeskKey
                },
            },
        ],
        removedZendeskKey: [
            null,
            {
                removeZendeskKey: () => {
                    teamLogic.actions.updateCurrentTeam({ zendesk_key: '' })
                    return null
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.testedZendeskKeyLoading, teamLogic.selectors.currentTeamLoading],
            (testedZendeskKeyLoading: boolean, currentTeamLoading: boolean) =>
                testedZendeskKeyLoading || currentTeamLoading,
        ],
    }),
    listeners(() => ({
        testZendeskKeySuccess: ({ testedZendeskKey }) => {
            if (testedZendeskKey) {
                teamLogic.actions.updateCurrentTeam({ zendesk_key: testedZendeskKey })
            }
        },
        testZendeskKeyFailure: ({ error }) => {
            lemonToast.error(capitalizeFirstLetter(error))
        },
    })),
])
