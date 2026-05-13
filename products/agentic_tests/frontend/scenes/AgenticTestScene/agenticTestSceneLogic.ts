import { actions, events, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import {
    AgenticTest,
    AgenticTestAssertion,
    AgenticTestAssertionType,
    AgenticTestDraft,
    AgenticTestRun,
    defaultAssertion,
} from '../../types'
import type { agenticTestSceneLogicType } from './agenticTestSceneLogicType'

export interface AgenticTestSceneProps {
    id: string | 'new'
}

const baseUrl = (): string => `api/projects/${getCurrentTeamId()}/agentic_tests/`
const runsUrl = (): string => `api/projects/${getCurrentTeamId()}/agentic_test_runs/`

const emptyDraft: AgenticTestDraft = {
    name: '',
    description: '',
    target_url: '',
    prompt: '',
    status: 'proposed',
    assertions: [],
}

export const agenticTestSceneLogic = kea<agenticTestSceneLogicType>([
    path((key) => [
        'products',
        'agentic_tests',
        'frontend',
        'scenes',
        'AgenticTestScene',
        'agenticTestSceneLogic',
        key,
    ]),
    props({} as AgenticTestSceneProps),
    key((p) => p.id ?? 'new'),
    actions({
        runNow: true,
        activate: true,
        pause: true,
        addAssertion: (assertionType: AgenticTestAssertionType) => ({ assertionType }),
        updateAssertion: (index: number, patch: Partial<AgenticTestAssertion>) => ({ index, patch }),
        removeAssertion: (index: number) => ({ index }),
    }),
    loaders(({ props }) => ({
        test: [
            null as AgenticTest | null,
            {
                loadTest: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }
                    return await api.get<AgenticTest>(`${baseUrl()}${props.id}/`)
                },
            },
        ],
        runs: [
            [] as AgenticTestRun[],
            {
                loadRuns: async () => {
                    if (!props.id || props.id === 'new') {
                        return []
                    }
                    const response = await api.get<{ results: AgenticTestRun[] }>(
                        `${runsUrl()}?agentic_test=${props.id}`
                    )
                    return response.results
                },
            },
        ],
    })),
    forms(({ props, actions }) => ({
        testForm: {
            defaults: emptyDraft as AgenticTestDraft,
            submit: async (draft) => {
                if (!draft.name?.trim()) {
                    lemonToast.error('Name is required')
                    return
                }
                if (!draft.target_url?.trim()) {
                    lemonToast.error('Target URL is required')
                    return
                }
                if (!draft.prompt?.trim()) {
                    lemonToast.error('Prompt is required')
                    return
                }
                const isNew = !props.id || props.id === 'new'
                const saved = isNew
                    ? await api.create<AgenticTest>(baseUrl(), draft)
                    : await api.update<AgenticTest>(`${baseUrl()}${props.id}/`, draft)
                lemonToast.success(isNew ? 'Agentic test created' : 'Agentic test saved')
                if (isNew && saved.id) {
                    router.actions.push(`/agentic_tests/${saved.id}`)
                } else {
                    actions.loadTest()
                }
            },
        },
    })),
    listeners(({ props, actions, values }) => ({
        loadTestSuccess: ({ test }) => {
            if (!test) {
                return
            }
            actions.setTestFormValues({
                name: test.name,
                description: test.description,
                target_url: test.target_url,
                prompt: test.prompt,
                status: test.status,
                assertions: test.assertions ?? [],
                source_replay_id: test.source_replay_id,
            })
            actions.loadRuns()
        },
        addAssertion: ({ assertionType }) => {
            const current = values.testForm.assertions ?? []
            actions.setTestFormValue('assertions', [...current, defaultAssertion(assertionType)])
        },
        updateAssertion: ({ index, patch }) => {
            const current = [...(values.testForm.assertions ?? [])]
            current[index] = { ...current[index], ...patch } as AgenticTestAssertion
            actions.setTestFormValue('assertions', current)
        },
        removeAssertion: ({ index }) => {
            const current = [...(values.testForm.assertions ?? [])]
            current.splice(index, 1)
            actions.setTestFormValue('assertions', current)
        },
        runNow: async () => {
            if (!props.id || props.id === 'new') {
                lemonToast.warning('Save the test before running it')
                return
            }
            await api.create(`${baseUrl()}${props.id}/run_now/`, {})
            lemonToast.success('Run queued — refreshing history')
            actions.loadRuns()
            actions.loadTest()
        },
        activate: async () => {
            if (!props.id || props.id === 'new') {
                return
            }
            await api.create(`${baseUrl()}${props.id}/activate/`, {})
            actions.loadTest()
        },
        pause: async () => {
            if (!props.id || props.id === 'new') {
                return
            }
            await api.create(`${baseUrl()}${props.id}/pause/`, {})
            actions.loadTest()
        },
    })),
    selectors({
        isNew: [(_, p) => [p.id as any], (id) => !id || id === 'new'],
        logsUrl: [
            (_, p) => [p.id as any],
            (id) => {
                if (!id || id === 'new') {
                    return null
                }
                return `/logs?q=${encodeURIComponent(`agentic_test_id:"${id}"`)}`
            },
        ],
    }),
    events(({ actions, props }) => ({
        afterMount: () => {
            if (props.id && props.id !== 'new') {
                actions.loadTest()
                actions.loadRuns()
            }
        },
    })),
])
