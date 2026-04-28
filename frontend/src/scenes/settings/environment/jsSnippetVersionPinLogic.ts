import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { jsSnippetVersionPinLogicType } from './jsSnippetVersionPinLogicType'

export interface VersionPinResponse {
    requested_version: string | null
    resolved_version: string | null
}

export const jsSnippetVersionPinLogic = kea<jsSnippetVersionPinLogicType>([
    path(['scenes', 'settings', 'environment', 'jsSnippetVersionPinLogic']),
    actions({
        setLocalPin: (localPin: string) => ({ localPin }),
    }),
    loaders(({ actions }) => ({
        versionPinResponse: [
            null as VersionPinResponse | null,
            {
                loadVersionPin: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await api.get(`api/projects/${teamId}/js-snippet/version`)
                },
                saveVersionPin: async ({ pin }: { pin: string | null }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const response = await api.update(`api/projects/${teamId}/js-snippet/version`, {
                        js_snippet_version: pin,
                    })
                    lemonToast.success('Snippet version updated')
                    actions.setLocalPin(response.requested_version ?? '')
                    return response
                },
            },
        ],
    })),
    reducers({
        localPin: [
            '' as string,
            {
                setLocalPin: (_, { localPin }) => localPin,
                loadVersionPinSuccess: (_, { versionPinResponse }) => versionPinResponse?.requested_version ?? '',
            },
        ],
    }),
    listeners(() => ({
        saveVersionPinFailure: ({ error }) => {
            lemonToast.error(error || 'Failed to update version')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadVersionPin()
    }),
])
