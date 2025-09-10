import { actions, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { afterMount } from 'kea'

import api from 'lib/api'

import type { streamlitAppsLogicType } from './streamlitAppsLogicType'

export interface StreamlitApp {
    id: string
    name: string
    description: string
    container_id: string
    container_status: 'pending' | 'running' | 'stopped' | 'failed'
    port: number | null
    internal_url: string
    public_url: string
    last_accessed: string | null
    created_by: {
        id: number
        email: string
        first_name: string
        last_name: string
    }
    created_at: string
    updated_at: string
}

export interface StreamlitAppsLogicProps {
    // Add any props your logic needs
}

export const streamlitAppsLogic = kea<streamlitAppsLogicType>([
    path(['scenes', 'streamlit', 'streamlitAppsLogic']),
    props({} as StreamlitAppsLogicProps),

    actions({
        loadApps: true,
        createApp: (name: string, description?: string) => ({ name, description }),
        deleteApp: (appId: string) => ({ appId }),
        refreshApps: true,
        openApp: (appId: string) => ({ appId }),
        closeApp: true,
    }),

    loaders(({ actions }) => ({
        apps: [
            [] as StreamlitApp[],
            {
                loadApps: async () => {
                    const response = await api.get('/api/projects/@current/streamlit_apps/')
                    return response.results || []
                },
                createApp: async ({ name, description }) => {
                    const newApp = await api.create('/api/projects/@current/streamlit_apps/', {
                        name,
                        description: description || '',
                    })
                    actions.loadApps()
                    return newApp
                },
                deleteApp: async ({ appId }) => {
                    await api.delete(`/api/projects/@current/streamlit_apps/${appId}/`)
                    actions.loadApps()
                    return []
                },
                refreshApps: async () => {
                    const response = await api.get('/api/projects/@current/streamlit_apps/')
                    return response.results || []
                },
            },
        ],
    })),

    reducers({
        isLoading: [
            false,
            {
                loadApps: () => true,
                loadAppsSuccess: () => false,
                loadAppsFailure: () => false,
            },
        ],
        openAppId: [
            null as string | null,
            {
                openApp: (_, { appId }) => appId,
                closeApp: () => null,
            },
        ],
    }),

    selectors({
        runningApps: [
            (s) => [s.apps],
            (apps: StreamlitApp[]) => apps.filter((app) => app.container_status === 'running'),
        ],
        pendingApps: [
            (s) => [s.apps],
            (apps: StreamlitApp[]) => apps.filter((app) => app.container_status === 'pending'),
        ],
        failedApps: [
            (s) => [s.apps],
            (apps: StreamlitApp[]) => apps.filter((app) => app.container_status === 'failed'),
        ],
        openApp: [
            (s) => [s.apps, s.openAppId],
            (apps: StreamlitApp[], openAppId: string | null) => 
                openAppId ? apps.find(app => app.id === openAppId) || null : null,
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadApps()
    }),
])
