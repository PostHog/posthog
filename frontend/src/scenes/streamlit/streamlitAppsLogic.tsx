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
    entrypoint_file: string | null
    requirements_file: string | null
    app_type: 'default' | 'custom'
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
        createApp: (name: string, description?: string, appType?: 'default' | 'custom', entrypointFile?: File, requirementsFile?: File) => ({ 
            name, description, appType, entrypointFile, requirementsFile 
        }),
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
                    try {
                        const response = await api.get('/api/projects/@current/streamlit_apps/')
                        return response.results || []
                    } catch (error) {
                        console.error('Failed to load apps:', error)
                        return []
                    }
                },
                createApp: async ({ name, description, appType, entrypointFile, requirementsFile }) => {
                    const formData = new FormData()
                    formData.append('name', name)
                    formData.append('description', description || '')
                    formData.append('app_type', appType || 'default')
                    
                    if (entrypointFile) {
                        formData.append('entrypoint_file', entrypointFile)
                    }
                    if (requirementsFile) {
                        formData.append('requirements_file', requirementsFile)
                    }
                    
                    const newApp = await api.create('/api/projects/@current/streamlit_apps/', formData)
                    // Reload apps after creation
                    const response = await api.get('/api/projects/@current/streamlit_apps/')
                    return response.results || []
                },
                deleteApp: async ({ appId }) => {
                    await api.delete(`/api/projects/@current/streamlit_apps/${appId}/`)
                    // Reload apps after deletion
                    const response = await api.get('/api/projects/@current/streamlit_apps/')
                    return response.results || []
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
            (apps: StreamlitApp[]) => apps?.filter((app) => app.container_status === 'running') || [],
        ],
        pendingApps: [
            (s) => [s.apps],
            (apps: StreamlitApp[]) => apps?.filter((app) => app.container_status === 'pending') || [],
        ],
        failedApps: [
            (s) => [s.apps],
            (apps: StreamlitApp[]) => apps?.filter((app) => app.container_status === 'failed') || [],
        ],
        openApp: [
            (s) => [s.apps, s.openAppId],
            (apps: StreamlitApp[], openAppId: string | null) => 
                openAppId && apps ? apps.find(app => app.id === openAppId) || null : null,
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadApps()
    }),
])
