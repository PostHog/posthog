import { actions, connect, kea, listeners, path } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { conversationsSettingsLogicType } from './conversationsSettingsLogicType'

export const conversationsSettingsLogic = kea<conversationsSettingsLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'conversationsSettingsLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        generateNewToken: true,
    }),
    listeners(({ values, actions }) => ({
        generateNewToken: async () => {
            const response = await api.projects.generateConversationsPublicToken(values.currentTeam?.id)
            actions.updateCurrentTeam(response)
            lemonToast.success('New token generated')
        },
    })),
])
