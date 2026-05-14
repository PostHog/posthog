import { actions, events, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { AgenticTestAssertion, AgenticTestAssertionType, defaultAssertion } from '../../assertions'
import {
    agenticTestRunsList,
    agenticTestsActivateCreate,
    agenticTestsCreate,
    agenticTestsPartialUpdate,
    agenticTestsPauseCreate,
    agenticTestsRejectCreate,
    agenticTestsRetrieve,
    agenticTestsRunNowCreate,
} from '../../generated/api'
import { AgenticTestApi, AgenticTestRunApi } from '../../generated/api.schemas'
import type { agenticTestSceneLogicType } from './agenticTestSceneLogicType'

export type AgenticTest = Omit<AgenticTestApi, 'assertions'> & { assertions: AgenticTestAssertion[] }
export type AgenticTestRun = AgenticTestRunApi

export interface AgenticTestDraft {
    name: string
    description: string
    target_url: string
    prompt: string
    status: AgenticTestApi['status']
    assertions: AgenticTestAssertion[]
    source_replay_id?: string | null
    schedule_cron: string
}

export interface AgenticTestSceneProps {
    id: string | 'new'
}

const projectId = (): string => String(getCurrentTeamId())

const emptyDraft: AgenticTestDraft = {
    name: 'New agentic test',
    description: '',
    target_url: '',
    prompt: '',
    status: 'proposed',
    assertions: [],
    schedule_cron: '',
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
        clearChanges: true,
        reject: true,
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
                    return (await agenticTestsRetrieve(projectId(), props.id)) as unknown as AgenticTest
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
                    const response = await agenticTestRunsList(projectId(), {
                        agentic_test: props.id,
                    } as never)
                    return [...response.results]
                },
            },
        ],
    })),
    forms(({ props, actions }) => ({
        testForm: {
            defaults: emptyDraft as AgenticTestDraft,
            submit: async (draft) => {
                const name = draft.name?.trim() || 'New agentic test'
                if (!draft.target_url?.trim()) {
                    lemonToast.error('Target URL is required')
                    return
                }
                if (!draft.prompt?.trim()) {
                    lemonToast.error('Prompt is required')
                    return
                }
                draft = { ...draft, name }
                const isNew = !props.id || props.id === 'new'
                const saved = (isNew
                    ? await agenticTestsCreate(projectId(), draft as any)
                    : await agenticTestsPartialUpdate(projectId(), props.id, draft as any)) as unknown as AgenticTest
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
            actions.resetTestForm({
                name: test.name,
                description: test.description,
                target_url: test.target_url,
                prompt: test.prompt,
                status: test.status,
                assertions: test.assertions ?? [],
                source_replay_id: test.source_replay_id,
                schedule_cron: (test as any).schedule_cron ?? '',
            })
            actions.loadRuns()
        },
        clearChanges: () => {
            const test = values.test
            if (!test) {
                actions.resetTestForm()
                return
            }
            actions.resetTestForm({
                name: test.name,
                description: test.description,
                target_url: test.target_url,
                prompt: test.prompt,
                status: test.status,
                assertions: test.assertions ?? [],
                source_replay_id: test.source_replay_id,
                schedule_cron: (test as any).schedule_cron ?? '',
            })
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
            await agenticTestsRunNowCreate(projectId(), props.id)
            lemonToast.success('Run queued — refreshing history')
            actions.loadRuns()
            actions.loadTest()
        },
        activate: async () => {
            if (!props.id || props.id === 'new') {
                return
            }
            await agenticTestsPartialUpdate(projectId(), props.id, values.testForm as any)
            await agenticTestsActivateCreate(projectId(), props.id)
            actions.loadTest()
        },
        pause: async () => {
            if (!props.id || props.id === 'new') {
                return
            }
            await agenticTestsPauseCreate(projectId(), props.id)
            actions.loadTest()
        },
        reject: async () => {
            if (!props.id || props.id === 'new') {
                return
            }
            await agenticTestsRejectCreate(projectId(), props.id)
            lemonToast.success('Proposal rejected')
            router.actions.push('/agentic_tests')
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
        willChangeEnabledOnSave: [
            (s) => [s.testForm, s.test],
            (testForm, test) => {
                if (!test) {
                    return false
                }
                const draftEnabled = testForm.status === 'active'
                const persistedEnabled = test.status === 'active'
                return draftEnabled !== persistedEnabled
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
