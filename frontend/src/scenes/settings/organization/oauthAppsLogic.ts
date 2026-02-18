import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { OAuthApplicationType } from '~/types'

import type { oauthAppsLogicType } from './oauthAppsLogicType'

export interface OAuthAppFormValues {
    name: string
    redirect_uris_list: string[]
}

const defaultFormValues: OAuthAppFormValues = {
    name: '',
    redirect_uris_list: [],
}

export const oauthAppsLogic = kea<oauthAppsLogicType>([
    path(['scenes', 'settings', 'organization', 'oauthAppsLogic']),

    actions({
        setEditingAppId: (id: string | 'new' | null) => ({ id }),
        setNewRedirectUri: (uri: string) => ({ uri }),
        addRedirectUri: true,
        removeRedirectUri: (index: number) => ({ index }),
        copyToClipboard: (text: string, label: string) => ({ text, label }),
        setNewlyCreatedApp: (app: OAuthApplicationType | null) => ({ app }),
    }),

    reducers({
        editingAppId: [
            null as string | 'new' | null,
            {
                setEditingAppId: (_, { id }) => id,
            },
        ],
        newRedirectUri: [
            '',
            {
                setNewRedirectUri: (_, { uri }) => uri,
                addRedirectUri: () => '',
            },
        ],
        newlyCreatedApp: [
            null as OAuthApplicationType | null,
            {
                setEditingAppId: () => null,
                setNewlyCreatedApp: (_, { app }) => app,
            },
        ],
    }),

    loaders(({ values }) => ({
        oauthApps: [
            [] as OAuthApplicationType[],
            {
                loadOAuthApps: async () => {
                    const response = await api.organizationOAuthApplications.list()
                    return response.results
                },
                deleteOAuthApp: async (id: string) => {
                    await api.organizationOAuthApplications.delete(id)
                    lemonToast.success('OAuth application deleted')
                    return values.oauthApps.filter((app) => app.id !== id)
                },
            },
        ],
        rotatedSecret: [
            null as string | null,
            {
                rotateSecret: async (id: string) => {
                    const response = await api.organizationOAuthApplications.rotateSecret(id)
                    lemonToast.success('Client secret rotated')
                    return response.client_secret || null
                },
            },
        ],
    })),

    forms(({ actions, values }) => ({
        oauthAppForm: {
            defaults: defaultFormValues,
            errors: (values: OAuthAppFormValues) => ({
                name: !values.name ? 'Name is required' : undefined,
                redirect_uris_list:
                    values.redirect_uris_list.length === 0 ? 'At least one redirect URI is required' : undefined,
            }),
            submit: async (formValues) => {
                try {
                    if (values.editingAppId === 'new') {
                        const newApp = await api.organizationOAuthApplications.create({
                            name: formValues.name,
                            redirect_uris_list: formValues.redirect_uris_list,
                        })
                        lemonToast.success('OAuth application created')
                        actions.loadOAuthApps()
                        actions.setNewlyCreatedApp(newApp)
                    } else if (values.editingAppId) {
                        await api.organizationOAuthApplications.update(values.editingAppId, {
                            name: formValues.name,
                            redirect_uris_list: formValues.redirect_uris_list,
                        })
                        lemonToast.success('OAuth application updated')
                        actions.loadOAuthApps()
                        actions.setEditingAppId(null)
                    }
                } catch (e: any) {
                    const errorMessage = e.detail || e.message || 'Failed to save OAuth application'
                    lemonToast.error(errorMessage)
                    throw e
                }
            },
        },
    })),

    selectors({
        editingApp: [
            (s) => [s.oauthApps, s.editingAppId],
            (oauthApps, editingAppId): OAuthApplicationType | null => {
                if (!editingAppId || editingAppId === 'new') {
                    return null
                }
                return oauthApps.find((app) => app.id === editingAppId) || null
            },
        ],
        isNewApp: [(s) => [s.editingAppId], (editingAppId) => editingAppId === 'new'],
    }),

    listeners(({ actions, values }) => ({
        setEditingAppId: ({ id }) => {
            if (id === 'new') {
                actions.resetOauthAppForm()
            } else if (id) {
                const app = values.oauthApps.find((a) => a.id === id)
                if (app) {
                    actions.setOauthAppFormValues({
                        name: app.name,
                        redirect_uris_list: app.redirect_uris_list || [],
                    })
                }
            }
        },
        addRedirectUri: () => {
            const uri = values.newRedirectUri.trim()
            if (uri && !values.oauthAppForm.redirect_uris_list.includes(uri)) {
                actions.setOauthAppFormValue('redirect_uris_list', [...values.oauthAppForm.redirect_uris_list, uri])
            }
        },
        removeRedirectUri: ({ index }) => {
            const uris = [...values.oauthAppForm.redirect_uris_list]
            uris.splice(index, 1)
            actions.setOauthAppFormValue('redirect_uris_list', uris)
        },
        copyToClipboard: async ({ text, label }) => {
            await navigator.clipboard.writeText(text)
            lemonToast.success(`${label} copied to clipboard`)
        },
        setNewlyCreatedApp: () => {},
    })),

    afterMount(({ actions }) => {
        actions.loadOAuthApps()
    }),
])
