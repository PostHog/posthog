import { createParser } from 'eventsource-parser'
import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
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

/** One event emitted by the backend SSE stream for an in-flight agentic test run. */
export interface LiveRunEvent {
    event: string
    data: Record<string, any>
    receivedAt: number
}

export interface AgenticTestDraft {
    name: string
    description: string
    target_url: string
    prompt: string
    status: AgenticTestApi['status']
    assertions: AgenticTestAssertion[]
    source_replay_id?: string | null
    schedule_cron: string
    regions: string[]
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
    // Manually-created tests start enabled. `proposed` is reserved for AI-suggested tests
    // produced by the detect-flows path, which always go through accept/reject first.
    status: 'active',
    assertions: [],
    schedule_cron: '',
    regions: ['us-west-2'],
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
        streamRun: true,
        appendLiveEvent: (event: LiveRunEvent) => ({ event }),
        clearLiveEvents: true,
        setStreaming: (streaming: boolean) => ({ streaming }),
        activate: true,
        pause: true,
        clearChanges: true,
        reject: true,
        addAssertion: (assertionType: AgenticTestAssertionType) => ({ assertionType }),
        updateAssertion: (index: number, patch: Partial<AgenticTestAssertion>) => ({ index, patch }),
        removeAssertion: (index: number) => ({ index }),
    }),
    reducers({
        liveEvents: [
            [] as LiveRunEvent[],
            {
                appendLiveEvent: (state, { event }) => [...state, event],
                clearLiveEvents: () => [],
                streamRun: () => [],
            },
        ],
        streaming: [
            false,
            {
                streamRun: () => true,
                setStreaming: (_, { streaming }) => streaming,
            },
        ],
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
                if (!draft.regions || draft.regions.length === 0) {
                    lemonToast.error('Pick at least one region for this test to run from')
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
    listeners(({ props, actions, values, cache }) => ({
        // Poll runs every 3s while any run is in 'running' state, so the Runs tab
        // shows live progress (refresh-resilient — backend persists log_entries every
        // ~1.5s so a page reload picks the stream up right where it left off).
        loadRunsSuccess: () => {
            if (values.hasRunningRuns) {
                cache.disposables.add(() => {
                    const t = setTimeout(() => actions.loadRuns(), 3000)
                    return () => clearTimeout(t)
                }, 'pollRuns')
            }
        },
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
                regions: (test as any).regions ?? [],
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
                regions: (test as any).regions ?? [],
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
        streamRun: async () => {
            if (!props.id || props.id === 'new') {
                lemonToast.warning('Save the test before running it')
                return
            }
            const url = `/api/projects/${projectId()}/agentic_tests/${props.id}/stream/`
            try {
                const response = await api.createResponse(
                    url,
                    {},
                    {
                        headers: { Accept: 'text/event-stream' },
                    }
                )
                if (!response.ok) {
                    const body = await response.text().catch(() => '')
                    throw new Error(`HTTP ${response.status} ${response.statusText}: ${body.slice(0, 200)}`)
                }
                const reader = response.body?.getReader()
                if (!reader) {
                    throw new Error('Response had no readable body')
                }
                const decoder = new TextDecoder()
                const parser = createParser({
                    onEvent: ({ event, data }) => {
                        let parsed: Record<string, any> = {}
                        try {
                            parsed = data ? JSON.parse(data) : {}
                        } catch {
                            parsed = { _raw: data }
                        }
                        actions.appendLiveEvent({
                            event: event || 'message',
                            data: parsed,
                            receivedAt: Date.now(),
                        })
                    },
                })
                while (true) {
                    const { value, done } = await reader.read()
                    if (value) {
                        parser.feed(decoder.decode(value, { stream: true }))
                    }
                    if (done) {
                        break
                    }
                }
            } catch (err: any) {
                lemonToast.error(`Stream failed: ${err?.message ?? err}`)
            } finally {
                actions.setStreaming(false)
                actions.loadRuns()
                actions.loadTest()
            }
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
        hasRunningRuns: [(s) => [s.runs], (runs: AgenticTestRun[]) => runs.some((r) => r.status === 'running')],
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
