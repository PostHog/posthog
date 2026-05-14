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

// Mirror of the server-side validator in
// products/agent_stack/backend/serializers.py:parse_env. Keep these in sync so the
// UI rejects malformed env before the network round-trip.
const ENV_LINE_RE = /^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=/

export function validateEnv(env: string): string | undefined {
    if (!env) {
        return undefined
    }
    const seen = new Set<string>()
    const lines = env.split('\n')
    for (let i = 0; i < lines.length; i++) {
        const stripped = lines[i].trim()
        if (!stripped || stripped.startsWith('#')) {
            continue
        }
        if (!ENV_LINE_RE.test(lines[i])) {
            return `Line ${i + 1}: expected \`KEY=value\` (KEY must start with a letter or \`_\` and contain only letters, digits, or \`_\`).`
        }
        const key = lines[i]
            .replace(/^\s*(?:export\s+)?/, '')
            .split('=', 1)[0]
            .trim()
        if (seen.has(key)) {
            return `Line ${i + 1}: duplicate key \`${key}\`.`
        }
        seen.add(key)
    }
    return undefined
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
            errors: ({ name, env }) => ({
                name: !name?.trim() ? 'Name is required' : undefined,
                env: validateEnv(env),
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
