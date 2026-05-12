import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { getCurrentTeamId } from '~/lib/utils/getAppContext'

import type { watchedQuestionsLogicType } from './watchedQuestionsLogicType'

export type WatchedQuestionCadence = 'daily' | 'weekly' | 'monthly'
export type WatchedQuestionStatus = 'active' | 'paused' | 'archived'
export type WatchedQuestionRunState = 'ok' | 'drifted' | 'error' | 'skipped'
export type WatchedQuestionSeverity = 'none' | 'minor' | 'moderate' | 'significant'

export interface WatchedQuestionRun {
    id: string
    state: WatchedQuestionRunState
    severity: WatchedQuestionSeverity
    judge_summary: string
    narrative: string
    forked_conversation_id: string | null
    signal_emitted_at: string | null
    error: string
    created_at: string
}

export interface WatchedQuestion {
    id: string
    created_by: { id: number; first_name?: string; last_name?: string; email?: string } | null
    conversation_id: string
    human_message_id: string
    visualization_message_id: string
    title: string
    question_text: string
    baseline_summary: string
    baseline_captured_at: string
    cadence: WatchedQuestionCadence
    status: WatchedQuestionStatus
    next_run_at: string
    last_run_at: string | null
    repository: string
    recent_runs: WatchedQuestionRun[]
    created_at: string
    updated_at: string
}

export interface CreateWatchedQuestionPayload {
    conversation_id: string
    human_message_id: string
    visualization_message_id: string
    title: string
    cadence?: WatchedQuestionCadence
    repository?: string
}

const apiBase = (): string => `api/environments/${getCurrentTeamId()}/posthog_ai/watched_questions`

export const watchedQuestionsLogic = kea<watchedQuestionsLogicType>([
    path(['scenes', 'max', 'watched', 'watchedQuestionsLogic']),
    actions({
        openPanel: true,
        closePanel: true,
        togglePanel: true,
        pauseQuestion: (id: string) => ({ id }),
        resumeQuestion: (id: string) => ({ id }),
        archiveQuestion: (id: string) => ({ id }),
        runNow: (id: string) => ({ id }),
        markQuestionUpdated: (question: WatchedQuestion) => ({ question }),
    }),
    reducers({
        panelOpen: [
            false,
            {
                openPanel: () => true,
                closePanel: () => false,
                togglePanel: (state) => !state,
            },
        ],
    }),
    loaders(({ values }) => ({
        watchedQuestions: [
            [] as WatchedQuestion[],
            {
                loadWatchedQuestions: async () => {
                    const response = await api.get<{ results: WatchedQuestion[] }>(apiBase() + '/')
                    return response.results || []
                },
                createWatchedQuestion: async (payload: CreateWatchedQuestionPayload) => {
                    const created = await api.create<WatchedQuestion>(apiBase() + '/', payload)
                    return [created, ...values.watchedQuestions]
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        pauseQuestion: async ({ id }) => {
            try {
                const updated = await api.create<WatchedQuestion>(`${apiBase()}/${id}/pause/`, {})
                actions.markQuestionUpdated(updated)
                lemonToast.success('Watched question paused')
            } catch {
                lemonToast.error('Failed to pause watched question')
            }
        },
        resumeQuestion: async ({ id }) => {
            try {
                const updated = await api.create<WatchedQuestion>(`${apiBase()}/${id}/resume/`, {})
                actions.markQuestionUpdated(updated)
                lemonToast.success('Watched question resumed')
            } catch {
                lemonToast.error('Failed to resume watched question')
            }
        },
        archiveQuestion: async ({ id }) => {
            try {
                await api.delete(`${apiBase()}/${id}/`)
                actions.loadWatchedQuestions()
                lemonToast.success('Watched question archived')
            } catch {
                lemonToast.error('Failed to archive watched question')
            }
        },
        runNow: async ({ id }) => {
            try {
                await api.create(`${apiBase()}/${id}/run_now/`, {})
                lemonToast.success('Drift check queued — refresh in a few minutes')
            } catch {
                lemonToast.error('Failed to enqueue manual drift check')
            }
        },
        createWatchedQuestionSuccess: () => {
            lemonToast.success('Watching this answer')
        },
        createWatchedQuestionFailure: ({ error }) => {
            lemonToast.error(error?.message || 'Failed to start watching this answer')
        },
    })),
    reducers({
        watchedQuestions: {
            markQuestionUpdated: (state, { question }) =>
                state.map((existing) => (existing.id === question.id ? question : existing)),
        },
    }),
    selectors({
        activeQuestions: [(s) => [s.watchedQuestions], (questions) => questions.filter((q) => q.status === 'active')],
        pausedQuestions: [(s) => [s.watchedQuestions], (questions) => questions.filter((q) => q.status === 'paused')],
        questionsNeedingAttention: [
            (s) => [s.watchedQuestions],
            (questions) =>
                questions.filter((q) => q.recent_runs.some((r) => r.state === 'drifted' && r.severity !== 'minor')),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadWatchedQuestions()
    }),
])
