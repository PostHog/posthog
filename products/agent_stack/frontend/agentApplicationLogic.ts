import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type { agentApplicationLogicType } from './agentApplicationLogicType'
import {
    agentApplicationsEnvUpdate,
    agentApplicationsPartialUpdate,
    agentApplicationsRetrieve,
    agentApplicationsRevisionsList,
    agentApplicationsSessionsList,
} from './generated/api'
import type {
    AgentApplicationApi,
    AgentApplicationRevisionApi,
    AgentApplicationSessionApi,
} from './generated/api.schemas'

export enum AgentApplicationTab {
    Overview = 'overview',
    Settings = 'settings',
}

export interface AgentApplicationLogicProps {
    slug: string
}

export interface SettingsFormValues {
    name: string
    description: string
    env: string
}

export const agentApplicationLogic = kea<agentApplicationLogicType>([
    path(['products', 'agent_stack', 'frontend', 'agentApplicationLogic']),
    props({} as AgentApplicationLogicProps),
    key(({ slug }) => slug),

    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setActiveTab: (tab: AgentApplicationTab) => ({ tab }),
        setApplicationMissing: true,
    }),

    reducers({
        activeTab: [
            AgentApplicationTab.Overview as AgentApplicationTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        applicationMissing: [
            false,
            {
                setApplicationMissing: () => true,
            },
        ],
    }),

    loaders(({ props, values, actions }) => ({
        application: [
            null as AgentApplicationApi | null,
            {
                loadApplication: async () => {
                    try {
                        return await agentApplicationsRetrieve(String(values.currentProjectId), props.slug)
                    } catch {
                        actions.setApplicationMissing()
                        return null
                    }
                },
            },
        ],
        revisions: [
            [] as AgentApplicationRevisionApi[],
            {
                loadRevisions: async () => {
                    const response = await agentApplicationsRevisionsList(
                        String(values.currentProjectId),
                        props.slug,
                        {}
                    )
                    return response.results
                },
            },
        ],
        sessions: [
            [] as AgentApplicationSessionApi[],
            {
                loadSessions: async () => {
                    const response = await agentApplicationsSessionsList(
                        String(values.currentProjectId),
                        props.slug,
                        {}
                    )
                    return response.results
                },
            },
        ],
    })),

    selectors({
        liveRevision: [
            (s) => [s.revisions],
            (revisions: AgentApplicationRevisionApi[]) => revisions.find((r) => r.deployment_status === 'live') ?? null,
        ],
        previewRevisions: [
            (s) => [s.revisions],
            (revisions: AgentApplicationRevisionApi[]) => revisions.filter((r) => r.deployment_status === 'preview'),
        ],
        sessionStats: [
            (s) => [s.sessions],
            (sessions: AgentApplicationSessionApi[]) => {
                const stats = { total: sessions.length, running: 0, succeeded: 0, failed: 0 }
                for (const session of sessions) {
                    if (session.state === 'running' || session.state === 'available') {
                        stats.running += 1
                    } else if (session.state === 'completed') {
                        stats.succeeded += 1
                    } else if (session.state === 'failed') {
                        stats.failed += 1
                    }
                }
                return stats
            },
        ],
    }),

    forms(({ values, props, actions }) => ({
        settings: {
            defaults: { name: '', description: '', env: '' } as SettingsFormValues,
            errors: ({ name }) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                const projectId = String(values.currentProjectId)
                await agentApplicationsPartialUpdate(projectId, props.slug, {
                    name: payload.name,
                    description: payload.description,
                })
                // Env upload is replace-only and write-only — the redacted display is
                // never the source of truth, so we only PUT when the user typed something
                // new into the replace textarea.
                if (payload.env.trim().length > 0) {
                    await agentApplicationsEnvUpdate(projectId, props.slug, { env: payload.env })
                }
                await breakpoint(1)
                lemonToast.success('Settings saved')
                actions.loadApplication()
                actions.setSettingsValue('env', '')
            },
        },
    })),

    listeners(({ actions }) => ({
        loadApplicationSuccess: ({ application }) => {
            if (application) {
                actions.setSettingsValues({
                    name: application.name,
                    description: application.description || '',
                    env: '',
                })
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadApplication()
        actions.loadRevisions()
        actions.loadSessions()
    }),
])
