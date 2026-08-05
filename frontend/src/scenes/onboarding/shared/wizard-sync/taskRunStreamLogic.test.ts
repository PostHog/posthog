import { MOCK_TEAM_ID } from 'lib/api.mock'
import { installMockEventSource, MockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import {
    DEFAULT_POLLING_INTERVAL_SECS,
    jitteredIntervalMs,
    MAX_POLLING_INTERVAL_SECS,
    POLL_JITTER_RATIO,
    resolvePollingIntervalMs,
    SSE_RECONNECT_BASE_MS,
    SSE_RECONNECT_MAX_MS,
    sseReconnectDelayMs,
} from 'lib/wizard-sync/pollLoop'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { tasksActiveWizardRunRetrieve, tasksRunsRetrieve } from 'products/tasks/frontend/generated/api'
import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { activeCloudRunLogic } from './activeCloudRunLogic'
import {
    cloudRunCompletionReport,
    mergeProgressStep,
    NO_STATE_STALL_MS,
    parseStreamErrorMessage,
    parseTaskRunStreamMessage,
    TaskRunProgressStep,
    taskRunDetailToStreamState,
    taskRunPrUrl,
    taskRunStreamLogic,
    TaskRunStreamState,
} from './taskRunStreamLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    getTasksRunsStreamRetrieveUrl: jest.fn(() => '/mock-run-stream'),
    tasksRunsRetrieve: jest.fn(),
    tasksActiveWizardRunRetrieve: jest.fn(),
    tasksRunsCancelCreate: jest.fn(),
}))

const mockActiveWizardRun = tasksActiveWizardRunRetrieve as jest.Mock
const mockRunRetrieve = tasksRunsRetrieve as jest.Mock

function step(overrides: Partial<TaskRunProgressStep> = {}): TaskRunProgressStep {
    return {
        step: 'clone',
        status: 'in_progress',
        label: 'Cloning repository',
        group: 'setup',
        detail: null,
        ...overrides,
    }
}

function runState(overrides: Partial<TaskRunStreamState> = {}): TaskRunStreamState {
    return {
        status: 'in_progress',
        stage: 'wizard',
        output: null,
        branch: null,
        error_message: null,
        updated_at: '2026-01-01T00:05:00Z',
        completed_at: null,
        ...overrides,
    }
}

describe('taskRunStreamLogic helpers', () => {
    describe('mergeProgressStep', () => {
        it('appends a new step', () => {
            expect(mergeProgressStep([], step())).toEqual([step()])
        })

        it('updates an existing (group, step) in place, preserving order', () => {
            const clone = step({ step: 'clone' })
            const wizard = step({ step: 'wizard', label: 'Running wizard' })
            const cloneDone = step({ step: 'clone', status: 'completed', label: 'Cloned' })
            expect(mergeProgressStep([clone, wizard], cloneDone)).toEqual([cloneDone, wizard])
        })

        it('treats the same step name in a different group as distinct', () => {
            const inSetup = step({ step: 'open', group: 'setup' })
            const inPr = step({ step: 'open', group: 'pr_create' })
            expect(mergeProgressStep([inSetup], inPr)).toEqual([inSetup, inPr])
        })
    })

    describe('parseTaskRunStreamMessage', () => {
        it('parses a task_run_state event with all fields', () => {
            const raw = JSON.stringify({
                type: 'task_run_state',
                status: 'failed',
                stage: 'wizard',
                output: { pr_url: 'https://x/pull/1' },
                branch: 'main',
                error_message: 'boom',
                updated_at: '2026-01-01T00:00:00Z',
                completed_at: '2026-01-01T00:01:00Z',
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'state',
                state: {
                    status: 'failed',
                    stage: 'wizard',
                    output: { pr_url: 'https://x/pull/1' },
                    branch: 'main',
                    error_message: 'boom',
                    updated_at: '2026-01-01T00:00:00Z',
                    completed_at: '2026-01-01T00:01:00Z',
                },
            })
        })

        it('defaults missing optional task_run_state fields to null', () => {
            const raw = JSON.stringify({
                type: 'task_run_state',
                status: 'in_progress',
                updated_at: '2026-01-01T00:00:00Z',
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'state',
                state: {
                    status: 'in_progress',
                    stage: null,
                    output: null,
                    branch: null,
                    error_message: null,
                    updated_at: '2026-01-01T00:00:00Z',
                    completed_at: null,
                },
            })
        })

        it('parses a _posthog/progress notification into a step', () => {
            const raw = JSON.stringify({
                type: 'notification',
                notification: {
                    method: '_posthog/progress',
                    params: {
                        step: 'clone',
                        status: 'in_progress',
                        label: 'Cloning',
                        group: 'setup',
                        detail: 'shallow',
                    },
                },
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'step',
                step: { step: 'clone', status: 'in_progress', label: 'Cloning', group: 'setup', detail: 'shallow' },
            })
        })

        it('defaults a step with no detail to null', () => {
            const raw = JSON.stringify({
                type: 'notification',
                notification: {
                    method: '_posthog/progress',
                    params: { step: 'clone', status: 'completed', label: 'Cloned', group: 'setup' },
                },
            })
            expect(parseTaskRunStreamMessage(raw)).toEqual({
                kind: 'step',
                step: { step: 'clone', status: 'completed', label: 'Cloned', group: 'setup', detail: null },
            })
        })

        it.each([
            [
                'a non-progress notification',
                { type: 'notification', notification: { method: 'other', params: { step: 'x' } } },
            ],
            [
                'a progress notification without params',
                { type: 'notification', notification: { method: '_posthog/progress' } },
            ],
            ['a notification without a notification field', { type: 'notification' }],
            ['a keepalive', { type: 'keepalive' }],
            ['an unknown type', { type: 'whatever' }],
        ])('returns null for %s', (_name, payload) => {
            expect(parseTaskRunStreamMessage(JSON.stringify(payload))).toBeNull()
        })

        it('throws on invalid JSON', () => {
            expect(() => parseTaskRunStreamMessage('not json')).toThrow(SyntaxError)
        })
    })

    describe('resolvePollingIntervalMs', () => {
        it.each([
            ['a valid payload interval', { polling_interval_secs: 10 }, 10_000],
            ['a sub-minimum interval (floored so it cannot hammer the endpoint)', { polling_interval_secs: 0 }, 1000],
            ['a negative interval', { polling_interval_secs: -5 }, 1000],
            ['a non-numeric interval', { polling_interval_secs: 'fast' }, DEFAULT_POLLING_INTERVAL_SECS * 1000],
            ['a missing payload', null, DEFAULT_POLLING_INTERVAL_SECS * 1000],
            ['a payload without the key', {}, DEFAULT_POLLING_INTERVAL_SECS * 1000],
            [
                'an over-maximum interval (clamped so sync cannot silently stall)',
                { polling_interval_secs: 3600 },
                MAX_POLLING_INTERVAL_SECS * 1000,
            ],
            [
                'a huge interval that would overflow the int32 setTimeout delay and fire immediately',
                { polling_interval_secs: 1_700_000_000 },
                MAX_POLLING_INTERVAL_SECS * 1000,
            ],
        ])('resolves %s', (_name, payload, expectedMs) => {
            expect(resolvePollingIntervalMs(payload)).toBe(expectedMs)
        })
    })

    describe('sseReconnectDelayMs', () => {
        // A CLOSED EventSource never retries natively, so these delays are the only thing standing
        // between a dropped stream and a permanently dead run card.
        it.each([
            ['the first attempt starts at the base', 1, SSE_RECONNECT_BASE_MS],
            ['a zero attempt is treated as the first', 0, SSE_RECONNECT_BASE_MS],
            ['consecutive attempts back off exponentially', 3, SSE_RECONNECT_BASE_MS * 4],
            ['the backoff caps at the ceiling', 10, SSE_RECONNECT_MAX_MS],
        ])('%s', (_name, attempt, expectedMs) => {
            // Mid-roll jitter resolves to the un-jittered delay.
            expect(sseReconnectDelayMs(attempt, () => 0.5)).toBe(expectedMs)
        })

        it('jitters the delay so dropped clients do not reconnect in lockstep', () => {
            expect(sseReconnectDelayMs(1, () => 0)).toBe(SSE_RECONNECT_BASE_MS * (1 - POLL_JITTER_RATIO))
            expect(sseReconnectDelayMs(1, () => 1)).toBe(SSE_RECONNECT_BASE_MS * (1 + POLL_JITTER_RATIO))
        })
    })

    describe('jitteredIntervalMs', () => {
        it.each([
            ['the lower jitter bound', 0, 3000 * (1 - POLL_JITTER_RATIO)],
            ['the base cadence at mid-roll', 0.5, 3000],
            ['the upper jitter bound', 1, 3000 * (1 + POLL_JITTER_RATIO)],
        ])('spreads ticks within ±20%% — %s', (_name, roll, expectedMs) => {
            expect(jitteredIntervalMs(3000, () => roll)).toBe(expectedMs)
        })
    })

    describe('taskRunDetailToStreamState', () => {
        it('projects a REST snapshot onto the SSE state shape, coercing missing fields to null', () => {
            const dto = {
                id: 'run-1',
                task: 'task-1',
                stage: undefined,
                branch: undefined,
                status: 'in_progress',
                environment: 'sandbox',
                error_message: null,
                output: undefined,
                state: {},
                artifacts: [],
            } as unknown as TaskRunDetailDTOApi
            expect(taskRunDetailToStreamState(dto)).toEqual({
                status: 'in_progress',
                stage: null,
                output: null,
                branch: null,
                error_message: null,
                updated_at: '',
                completed_at: null,
            })
        })

        it('carries the terminal fields the completion report depends on', () => {
            const dto = {
                id: 'run-1',
                task: 'task-1',
                stage: 'pr',
                branch: 'posthog-setup',
                status: 'completed',
                environment: 'sandbox',
                error_message: null,
                output: { pr_url: 'https://x/pull/1' },
                state: {},
                artifacts: [],
                updated_at: '2026-01-01T00:05:00Z',
                completed_at: '2026-01-01T00:04:30Z',
            } as unknown as TaskRunDetailDTOApi
            expect(taskRunDetailToStreamState(dto)).toEqual({
                status: 'completed',
                stage: 'pr',
                output: { pr_url: 'https://x/pull/1' },
                branch: 'posthog-setup',
                error_message: null,
                updated_at: '2026-01-01T00:05:00Z',
                completed_at: '2026-01-01T00:04:30Z',
            })
        })
    })

    describe('parseStreamErrorMessage', () => {
        // The browser dispatches transport failures under the same `error` name, so a payload that
        // does not carry a message must not be mistaken for the server giving up on the stream.
        it.each([
            ['the server error payload', '{"error": "Stream not available"}', 'Stream not available'],
            ['a payload without an error field', '{"type": "task_run_state"}', null],
            ['a non-string error field', '{"error": 42}', null],
            ['invalid JSON', 'not json', null],
        ])('reads %s', (_name, rawData, expected) => {
            expect(parseStreamErrorMessage(rawData)).toBe(expected)
        })
    })

    describe('taskRunPrUrl', () => {
        it('prefers the terminal output url over the pr progress step', () => {
            const state = runState({ output: { pr_url: 'https://x/pull/2' } })
            const steps = [step({ step: 'pr', group: 'pr_create', detail: 'https://x/pull/1' })]
            expect(taskRunPrUrl(state, steps)).toBe('https://x/pull/2')
        })

        it('falls back to the pr progress step detail when the output has no url', () => {
            const steps = [step({ step: 'pr', group: 'pr_create', detail: 'https://x/pull/1' })]
            expect(taskRunPrUrl(runState(), steps)).toBe('https://x/pull/1')
        })

        it('ignores a pr step whose detail is not a url', () => {
            const steps = [step({ step: 'pr', group: 'pr_create', detail: 'Opening a pull request' })]
            expect(taskRunPrUrl(runState(), steps)).toBeNull()
        })

        it('returns null with no state and no pr step', () => {
            expect(taskRunPrUrl(null, [step()])).toBeNull()
        })
    })

    describe('cloudRunCompletionReport', () => {
        const startedAt = '2026-01-01T00:00:00Z'

        it('reports an observed transition into completed, with duration and the PR', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({
                    status: 'completed',
                    output: { pr_url: 'https://x/pull/1' },
                    completed_at: '2026-01-01T00:04:30Z',
                }),
                [],
                startedAt
            )
            expect(report).toEqual({
                status: 'completed',
                durationSeconds: 270,
                prOpened: true,
                prUrl: 'https://x/pull/1',
            })
        })

        it('reports a failed run with no PR opened', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'failed', error_message: 'boom', completed_at: '2026-01-01T00:04:30Z' }),
                [],
                startedAt
            )
            expect(report).toEqual({ status: 'failed', durationSeconds: 270, prOpened: false, prUrl: null })
        })

        it('takes the PR url from the pr progress step when the output lacks one', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'completed', completed_at: '2026-01-01T00:04:30Z' }),
                [step({ step: 'pr', group: 'pr_create', detail: 'https://x/pull/1' })],
                startedAt
            )
            expect(report).toMatchObject({ prOpened: true, prUrl: 'https://x/pull/1' })
        })

        it('falls back to updated_at for the duration when completed_at is missing', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'cancelled', updated_at: '2026-01-01T00:02:00Z' }),
                [],
                startedAt
            )
            expect(report).toMatchObject({ status: 'cancelled', durationSeconds: 120 })
        })

        it('reports a null duration without a kickoff timestamp', () => {
            const report = cloudRunCompletionReport(
                runState({ status: 'in_progress' }),
                runState({ status: 'completed', completed_at: '2026-01-01T00:04:30Z' }),
                [],
                undefined
            )
            expect(report).toMatchObject({ durationSeconds: null })
        })

        it.each([
            ['the update is not terminal', runState({ status: 'in_progress' }), runState({ status: 'queued' })],
            // A stream (re)connecting to a finished run replays the terminal state with no prior
            // observation — the backend task_run_* events cover unwatched completions.
            ['no previous state was observed', null, runState({ status: 'completed' })],
            [
                'the previous state was already terminal',
                runState({ status: 'completed' }),
                runState({ status: 'completed' }),
            ],
        ])('returns null when %s', (_name, previous, state) => {
            expect(cloudRunCompletionReport(previous, state, [], startedAt)).toBeNull()
        })
    })
})

// The first backoff step is 2s ±20%, so this window always contains the retry and never the second
// step's (4s -20% = 3.2s).
const PAST_FIRST_RECONNECT_MS = 2600
const RUN_STARTED_AT = '2026-01-01T00:00:00Z'

describe('taskRunStreamLogic transport', () => {
    let logic: ReturnType<typeof taskRunStreamLogic.build>
    let restoreEventSource: () => void
    let mounted = false

    beforeEach(async () => {
        // The run handle is persisted to localStorage, so a leftover from another test would decide
        // whether this run is the active one.
        window.localStorage.clear()
        initKeaTests()
        // Reconciliation must confirm the run under test, or it would clear the handle mid-test and
        // the stream would refuse to connect.
        mockActiveWizardRun.mockResolvedValue({
            task_id: 'task-1',
            run_id: 'run-1',
            status: 'in_progress',
            started_at: RUN_STARTED_AT,
        })
        mockRunRetrieve.mockReset()
        restoreEventSource = installMockEventSource()
        logic = taskRunStreamLogic({ taskId: 'task-1', runId: 'run-1' })
        logic.mount()
        mounted = true
        activeCloudRunLogic.actions.setActiveCloudRun('task-1', 'run-1', RUN_STARTED_AT, MOCK_TEAM_ID)
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: MOCK_TEAM_ID })
        jest.useFakeTimers()
    })

    afterEach(() => {
        if (mounted) {
            logic.unmount()
            mounted = false
        }
        jest.useRealTimers()
        restoreEventSource()
    })

    it('reconnects after a fatal close, which the browser never retries on its own', async () => {
        logic.actions.connect()
        MockEventSource.last().emitOpen()
        await expectLogic(logic).toDispatchActions(['connectionOpened'])

        MockEventSource.last().emitTransportError(MockEventSource.CLOSED)
        await expectLogic(logic).toDispatchActions(['connectionErrored'])
        expect(MockEventSource.instances).toHaveLength(1)

        jest.advanceTimersByTime(PAST_FIRST_RECONNECT_MS)
        await expectLogic(logic).toDispatchActions(['connect'])
        expect(MockEventSource.instances).toHaveLength(2)
    })

    it('backs off between consecutive fatal closes', async () => {
        logic.actions.connect()
        MockEventSource.last().emitTransportError(MockEventSource.CLOSED)
        await expectLogic(logic).toDispatchActions(['connectionErrored'])
        jest.advanceTimersByTime(PAST_FIRST_RECONNECT_MS)
        expect(MockEventSource.instances).toHaveLength(2)

        // No successful open in between, so the second attempt waits out the doubled window.
        MockEventSource.last().emitTransportError(MockEventSource.CLOSED)
        await expectLogic(logic).toDispatchActions(['connectionErrored'])
        jest.advanceTimersByTime(PAST_FIRST_RECONNECT_MS)
        expect(MockEventSource.instances).toHaveLength(2)

        jest.advanceTimersByTime(SSE_RECONNECT_MAX_MS)
        expect(MockEventSource.instances).toHaveLength(3)
    })

    it('leaves a transient drop to the browser, which retries it natively', async () => {
        logic.actions.connect()
        MockEventSource.last().emitOpen()
        await expectLogic(logic).toDispatchActions(['connectionOpened'])

        MockEventSource.last().emitTransportError(MockEventSource.CONNECTING)
        await expectLogic(logic).toDispatchActions(['connectionErrored'])

        jest.advanceTimersByTime(SSE_RECONNECT_MAX_MS)
        expect(MockEventSource.instances).toHaveLength(1)
    })

    it('cancels a pending reconnect on disconnect', async () => {
        logic.actions.connect()
        MockEventSource.last().emitTransportError(MockEventSource.CLOSED)
        await expectLogic(logic).toDispatchActions(['connectionErrored'])

        logic.actions.disconnect()
        jest.advanceTimersByTime(SSE_RECONNECT_MAX_MS)
        expect(MockEventSource.instances).toHaveLength(1)
    })

    it('cancels a pending reconnect on unmount', async () => {
        logic.actions.connect()
        MockEventSource.last().emitTransportError(MockEventSource.CLOSED)
        await expectLogic(logic).toDispatchActions(['connectionErrored'])

        logic.unmount()
        mounted = false
        jest.advanceTimersByTime(SSE_RECONNECT_MAX_MS)
        expect(MockEventSource.instances).toHaveLength(1)
    })

    // The run-detail fallback resolves outside kea, so its dispatches land a few microtasks after
    // the event that triggered it.
    const flushFallback = async (): Promise<void> => {
        for (let i = 0; i < 5; i++) {
            await Promise.resolve()
        }
    }

    const runDetail = (overrides: Record<string, unknown> = {}): TaskRunDetailDTOApi =>
        ({
            id: 'run-1',
            status: 'in_progress',
            stage: null,
            output: null,
            branch: null,
            error_message: null,
            updated_at: '2026-01-01T00:05:00Z',
            completed_at: null,
            ...overrides,
        }) as unknown as TaskRunDetailDTOApi

    it('settles a finished run from its detail when the server has no stream to serve', async () => {
        mockRunRetrieve.mockResolvedValue(
            runDetail({ status: 'completed', completed_at: '2026-01-01T00:06:00Z', output: { pr_url: 'https://x/1' } })
        )
        logic.actions.connect()
        MockEventSource.last().emitOpen()
        await expectLogic(logic).toDispatchActions(['connectionOpened'])

        // A named `error` event carries a payload; a transport failure does not. Only the former
        // means the server gave up waiting for the run's stream key.
        MockEventSource.last().emitNamed('error', '{"error": "Stream not available"}')
        await flushFallback()

        expect(mockRunRetrieve).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'task-1', 'run-1')
        expect(logic.values.taskRunState).toMatchObject({ status: 'completed' })
        expect(logic.values.isComplete).toBe(true)
        // Nothing more will ever be published for a finished run, so no retry is scheduled either.
        jest.advanceTimersByTime(SSE_RECONNECT_MAX_MS)
        expect(MockEventSource.instances).toHaveLength(1)
    })

    it('reconnects when the stream is unavailable but the run is still live', async () => {
        mockRunRetrieve.mockResolvedValue(runDetail({ status: 'in_progress' }))
        logic.actions.connect()
        MockEventSource.last().emitNamed('error', '{"error": "Stream not available"}')
        await flushFallback()

        expect(logic.values.taskRunState).toMatchObject({ status: 'in_progress' })
        jest.advanceTimersByTime(PAST_FIRST_RECONNECT_MS)
        expect(MockEventSource.instances).toHaveLength(2)
    })

    it('marks the stream dead when the run detail is gone for good', async () => {
        mockRunRetrieve.mockRejectedValue(new ApiError('not found', 404))
        logic.actions.connect()
        MockEventSource.last().emitNamed('error', '{"error": "Stream not available"}')
        await flushFallback()

        expect(logic.values.isStalled).toBe(true)
        // A deleted or access-revoked run is not worth retrying.
        jest.advanceTimersByTime(SSE_RECONNECT_MAX_MS)
        expect(MockEventSource.instances).toHaveLength(1)
    })

    it('reports a stall when the stream delivers no state at all', async () => {
        logic.actions.connect()
        MockEventSource.last().emitOpen()
        await expectLogic(logic).toDispatchActions(['connectionOpened'])

        jest.advanceTimersByTime(NO_STATE_STALL_MS)
        expect(logic.values.isStalled).toBe(true)
    })

    it('stamps lastActivityAt from delivered updates, never from connection events', async () => {
        logic.actions.connect()
        const stream = MockEventSource.last()
        stream.emitOpen()
        await expectLogic(logic).toDispatchActions(['connectionOpened'])
        // A stream that reconnects forever without ever saying anything must not read as a run that
        // is alive: only what the pipeline actually delivers counts as activity.
        expect(logic.values.lastActivityAt).toBeNull()

        stream.emitMessage(
            JSON.stringify({ type: 'task_run_state', status: 'in_progress', updated_at: '2026-01-01T00:05:00Z' })
        )
        await expectLogic(logic).toDispatchActions(['taskRunStateUpdated'])
        expect(logic.values.lastActivityAt).toEqual(expect.any(Number))
    })

    it('keeps the no-state stall through a scheduled reconnect', async () => {
        // The regression: a reconnect clears isStalled, and a per-connect timer would be re-armed
        // for another full window (or, armed once per lifetime, never re-armed at all), putting the
        // surfaces back on the eternal spinner with no way out.
        logic.actions.connect()
        MockEventSource.last().emitOpen()
        jest.advanceTimersByTime(NO_STATE_STALL_MS)
        expect(logic.values.isStalled).toBe(true)

        mockRunRetrieve.mockRejectedValue(new Error('network hiccup'))
        MockEventSource.last().emitNamed('error', '{"error": "Stream not available"}')
        await flushFallback()
        jest.advanceTimersByTime(PAST_FIRST_RECONNECT_MS)

        expect(MockEventSource.instances).toHaveLength(2)
        expect(logic.values.isStalled).toBe(true)
    })
})
