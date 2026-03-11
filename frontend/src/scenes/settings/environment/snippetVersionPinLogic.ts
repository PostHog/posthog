import { actions, kea, listeners, path, reducers } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { snippetVersionPinLogicType } from './snippetVersionPinLogicType'

export const snippetVersionPinLogic = kea<snippetVersionPinLogicType>([
    path(['scenes', 'settings', 'environment', 'snippetVersionPinLogic']),
    actions({
        loadVersionPin: true,
        loadVersionPinSuccess: (versionPin: string | null, resolvedVersion: string | null) => ({
            versionPin,
            resolvedVersion,
        }),
        saveVersionPin: (pin: string | null) => ({ pin }),
        saveVersionPinSuccess: (versionPin: string | null, resolvedVersion: string | null) => ({
            versionPin,
            resolvedVersion,
        }),
        setLoading: (loading: boolean) => ({ loading }),
        setSaving: (saving: boolean) => ({ saving }),
    }),
    reducers({
        versionPin: [
            null as string | null,
            {
                loadVersionPinSuccess: (_, { versionPin }) => versionPin,
                saveVersionPinSuccess: (_, { versionPin }) => versionPin,
            },
        ],
        resolvedVersion: [
            null as string | null,
            {
                loadVersionPinSuccess: (_, { resolvedVersion }) => resolvedVersion,
                saveVersionPinSuccess: (_, { resolvedVersion }) => resolvedVersion,
            },
        ],
        loading: [
            false,
            {
                setLoading: (_, { loading }) => loading,
            },
        ],
        saving: [
            false,
            {
                setSaving: (_, { saving }) => saving,
            },
        ],
    }),
    listeners(({ actions }) => ({
        loadVersionPin: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            actions.setLoading(true)
            try {
                const response = await api.get(`api/projects/${teamId}/snippet/version`)
                actions.loadVersionPinSuccess(response.snippet_version_pin, response.resolved_version)
            } catch {
                // Silently fail on load — versioning may not be configured
            } finally {
                actions.setLoading(false)
            }
        },
        saveVersionPin: async ({ pin }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            actions.setSaving(true)
            try {
                const response = await api.update(`api/projects/${teamId}/snippet/version`, {
                    snippet_version_pin: pin,
                })
                actions.saveVersionPinSuccess(response.snippet_version_pin, response.resolved_version)
                lemonToast.success('Snippet version pin updated')
            } catch (e: any) {
                const errorMessage = e?.data?.error || 'Failed to update version pin'
                lemonToast.error(errorMessage)
            } finally {
                actions.setSaving(false)
            }
        },
    })),
])
