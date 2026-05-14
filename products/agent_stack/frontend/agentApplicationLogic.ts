import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type { agentApplicationLogicType } from './agentApplicationLogicType'
import {
    agentApplicationsEnvUpdate,
    agentApplicationsPartialUpdate,
    agentApplicationsPromoteCreate,
    agentApplicationsRetrieve,
    agentApplicationsRevisionsList,
} from './generated/api'
import type { AgentApplicationApi, AgentApplicationRevisionApi } from './generated/api.schemas'

export enum AgentApplicationTab {
    Overview = 'overview',
    Settings = 'settings',
}

export interface AgentApplicationLogicProps {
    slug: string
}

export interface AgentSession {
    id: string
    status: string
    application_id: string
    revision_id: string | null
    created: string | null
    last_heartbeat: string | null
    last_transition: string | null
    transition_count: number
    state_byte_size: number | null
}

export interface RequiredSecret {
    key: string
    tool: string
    description?: string
}

export interface AgentConfig {
    prompt: string
    tools: string[]
    skills: string[]
    triggers: Array<{ id: string; type: string }>
    visibility: string
    required_secrets: RequiredSecret[]
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
        selectRevision: (revisionId: string | null) => ({ revisionId }),
        promoteRevision: (revisionId: string) => ({ revisionId }),
        saveSecrets: (keys: Record<string, string>) => ({ keys }),
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
        selectedRevisionId: [
            null as string | null,
            {
                selectRevision: (_, { revisionId }) => revisionId,
                loadRevisionsSuccess: () => null,
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
            [] as AgentSession[],
            {
                loadSessions: async () => {
                    const projectId = String(values.currentProjectId)
                    const url = `/api/projects/${projectId}/agent_applications/${encodeURIComponent(props.slug)}/sessions/`
                    const res = await fetch(url)
                    if (!res.ok) {
                        return []
                    }
                    const data = await res.json()
                    return (data.results ?? []) as AgentSession[]
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
        activeRevision: [
            (s) => [s.selectedRevisionId, s.revisions, s.liveRevision],
            (
                selectedId: string | null,
                revisions: AgentApplicationRevisionApi[],
                liveRevision: AgentApplicationRevisionApi | null
            ): AgentApplicationRevisionApi | null => {
                if (selectedId) {
                    return revisions.find((r) => r.id === selectedId) ?? null
                }
                return liveRevision
            },
        ],
        agentConfig: [
            (s) => [s.activeRevision],
            (revision: AgentApplicationRevisionApi | null): AgentConfig | null => {
                if (!revision?.top_level_config) {
                    return null
                }
                const cfg = revision.top_level_config as Record<string, unknown>
                return {
                    prompt: (cfg.prompt as string) ?? '',
                    tools: (cfg.tools as string[]) ?? [],
                    skills: (cfg.skills as string[]) ?? [],
                    triggers: (cfg.triggers as Array<{ id: string; type: string }>) ?? [],
                    visibility: (cfg.visibility as string) ?? 'private',
                    required_secrets: (cfg.required_secrets as RequiredSecret[]) ?? [],
                }
            },
        ],
        existingEnvKeys: [
            (s) => [s.application],
            (application: AgentApplicationApi | null): Set<string> => {
                if (!application?.env_redacted) {
                    return new Set()
                }
                return new Set(
                    application.env_redacted
                        .split('\n')
                        .filter((l: string) => l.includes('='))
                        .map((l: string) => l.split('=')[0])
                )
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

    listeners(({ actions, values, props }) => ({
        saveSecrets: async ({ keys }) => {
            const projectId = String(values.currentProjectId)
            const url = `/api/projects/${projectId}/agent_applications/${encodeURIComponent(props.slug)}/env/`
            const csrfToken = document.cookie.match(/posthog_csrftoken=([^;]+)/)?.[1] ?? ''
            const res = await fetch(url, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify({ keys }),
            })
            if (!res.ok) {
                const body = await res.json().catch(() => ({}))
                lemonToast.error(body.detail || 'Failed to save secrets')
                return
            }
            lemonToast.success('Secrets saved')
            actions.loadApplication()
        },
        promoteRevision: async ({ revisionId }) => {
            const projectId = String(values.currentProjectId)
            await agentApplicationsPromoteCreate(projectId, props.slug, {
                revision_id: revisionId,
            })
            lemonToast.success('Revision promoted to live')
            actions.loadRevisions()
            actions.selectRevision(null)
        },
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
