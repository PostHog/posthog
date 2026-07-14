import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { taskRunDefaultsLogic } from 'products/posthog_ai/frontend/logics/taskRunDefaultsLogic'
import {
    tasksConfigCreate,
    tasksConfigList,
    tasksMyConfigCreate,
    tasksMyConfigList,
} from 'products/tasks/frontend/generated/api'
import type {
    RuntimeAdapterEnumApi,
    TasksAIRunPreferencesApi,
    TasksResolvedAIRunDefaultsApi,
    TasksUserConfigResponseApi,
} from 'products/tasks/frontend/generated/api.schemas'

import type { taskAgentDefaultsLogicType } from './taskAgentDefaultsLogicType'

/** A model/effort pick being edited in the settings UI; null model = inherit (no default stored). */
export interface AIRunPreferenceDraft {
    model: string | null
    reasoning_effort: string | null
}

const EMPTY_DRAFT: AIRunPreferenceDraft = { model: null, reasoning_effort: null }

/** The runtime adapter is implied by the model family; the settings UI never asks for it separately. */
export function adapterForModel(model: string | null): RuntimeAdapterEnumApi | null {
    if (!model) {
        return null
    }
    return model.startsWith('claude') ? 'claude' : 'codex'
}

function draftFromStored(stored: TasksAIRunPreferencesApi | null | undefined): AIRunPreferenceDraft {
    return { model: stored?.model ?? null, reasoning_effort: stored?.reasoning_effort ?? null }
}

function payloadFromDraft(draft: AIRunPreferenceDraft): TasksAIRunPreferencesApi {
    return {
        runtime_adapter: adapterForModel(draft.model),
        model: draft.model,
        reasoning_effort: draft.model ? (draft.reasoning_effort as TasksAIRunPreferencesApi['reasoning_effort']) : null,
    }
}

export const taskAgentDefaultsLogic = kea<taskAgentDefaultsLogicType>([
    path(['scenes', 'settings', 'environment', 'taskAgentDefaultsLogic']),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    actions({
        setTeamDraft: (draft: Partial<AIRunPreferenceDraft>) => ({ draft }),
        setMyDraft: (draft: Partial<AIRunPreferenceDraft>) => ({ draft }),
        submitTeamDraft: true,
        submitMyDraft: true,
    }),

    reducers({
        teamDraft: [
            EMPTY_DRAFT,
            {
                setTeamDraft: (state, { draft }) => ({ ...state, ...draft }),
                loadTeamPreferencesSuccess: (_, { teamPreferences }) => draftFromStored(teamPreferences),
                saveTeamPreferencesSuccess: (_, { teamPreferences }) => draftFromStored(teamPreferences),
            },
        ],
        myDraft: [
            EMPTY_DRAFT,
            {
                setMyDraft: (state, { draft }) => ({ ...state, ...draft }),
                loadMyConfigSuccess: (_, { myConfig }) => draftFromStored(myConfig?.ai_run_preferences),
                saveMyPreferencesSuccess: (_, { myConfig }) => draftFromStored(myConfig?.ai_run_preferences),
            },
        ],
    }),

    loaders(({ values }) => ({
        teamPreferences: {
            __default: null as TasksAIRunPreferencesApi | null,
            loadTeamPreferences: async (): Promise<TasksAIRunPreferencesApi | null> => {
                if (values.currentProjectId == null) {
                    return null
                }
                return (await tasksConfigList(String(values.currentProjectId))).ai_run_preferences
            },
            saveTeamPreferences: async (
                preferences: TasksAIRunPreferencesApi
            ): Promise<TasksAIRunPreferencesApi | null> => {
                const response = await tasksConfigCreate(String(values.currentProjectId), preferences)
                lemonToast.success('Project default saved')
                return response.ai_run_preferences
            },
        },
        myConfig: {
            __default: null as TasksUserConfigResponseApi | null,
            loadMyConfig: async (): Promise<TasksUserConfigResponseApi | null> => {
                if (values.currentProjectId == null) {
                    return null
                }
                return await tasksMyConfigList(String(values.currentProjectId))
            },
            saveMyPreferences: async (
                preferences: TasksAIRunPreferencesApi
            ): Promise<TasksUserConfigResponseApi | null> => {
                const response = await tasksMyConfigCreate(String(values.currentProjectId), preferences)
                lemonToast.success('Your preference saved')
                return response
            },
        },
    })),

    selectors({
        resolvedDefaults: [
            (s) => [s.myConfig],
            (myConfig): TasksResolvedAIRunDefaultsApi | null => myConfig?.resolved_ai_run_defaults ?? null,
        ],
    }),

    listeners(({ actions, values }) => ({
        submitTeamDraft: () => {
            actions.saveTeamPreferences(payloadFromDraft(values.teamDraft))
        },
        submitMyDraft: () => {
            actions.saveMyPreferences(payloadFromDraft(values.myDraft))
        },
        // The team default feeds the resolved defaults shown in the "my preference" block, and
        // composers read the same resolution via taskRunDefaultsLogic — refresh both after a save.
        saveTeamPreferencesSuccess: () => {
            actions.loadMyConfig()
            taskRunDefaultsLogic.findMounted()?.actions.loadMyConfig()
        },
        saveMyPreferencesSuccess: () => {
            taskRunDefaultsLogic.findMounted()?.actions.loadMyConfig()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTeamPreferences()
        actions.loadMyConfig()
    }),
])
