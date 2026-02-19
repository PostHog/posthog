import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'

import type { cliLiveLogicType } from './cliLiveLogicType'

export const cliLiveLogic = kea<cliLiveLogicType>([
    path(['scenes', 'authentication', 'cliLiveLogic']),
    actions({
        setPort: (port: string) => ({ port }),
        selectProject: (projectId: number) => ({ projectId }),
        setError: (error: string) => ({ error }),
        setRedirected: (redirected: boolean) => ({ redirected }),
    }),
    reducers({
        port: [
            '' as string,
            {
                setPort: (_, { port }) => port,
            },
        ],
        selectedProjectId: [
            null as number | null,
            {
                selectProject: (_, { projectId }) => projectId,
            },
        ],
        error: [
            '' as string,
            {
                setError: (_, { error }) => error,
            },
        ],
        redirected: [
            false,
            {
                setRedirected: (_, { redirected }) => redirected,
            },
        ],
    }),
    loaders(() => ({
        projects: [
            [] as { id: number; name: string }[],
            {
                loadProjects: async () => {
                    const response = await api.get('api/projects/')
                    return response.results || []
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        loadProjectsSuccess: () => {
            if (values.projects.length === 1) {
                actions.selectProject(values.projects[0].id)
            }
        },
        selectProject: async ({ projectId }) => {
            if (!values.port) {
                actions.setError('Missing port parameter')
                return
            }
            const portNum = parseInt(values.port, 10)
            if (isNaN(portNum) || portNum < 1 || portNum > 65535 || String(portNum) !== values.port) {
                actions.setError('Invalid port parameter')
                return
            }

            try {
                const team = await api.get(`api/environments/${projectId}/`)
                const token = team.live_events_token
                if (!token) {
                    actions.setError('Live events token not available for this project')
                    return
                }
                const teamName = encodeURIComponent(team.name || '')
                const teamId = team.id
                const apiHost = encodeURIComponent(window.location.origin)
                window.location.href = `http://127.0.0.1:${portNum}/callback?token=${token}&team_name=${teamName}&team_id=${teamId}&api_host=${apiHost}`
                actions.setRedirected(true)
            } catch (e: any) {
                actions.setError(e?.detail || 'Failed to fetch project details')
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/cli/live': (_, searchParams) => {
            const port = searchParams.port
            if (port) {
                actions.setPort(port)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadProjects()
    }),
])
