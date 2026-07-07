import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import {
    cloudProgress,
    isSessionFresh,
    localProgress,
    resetWizardSyncTelemetryForTests,
    runLocalSessionBookkeeping,
} from './installationProgressLogic'

// Matches the fixtures' timestamps so sessions read as fresh where intended.
const NOW = new Date('2026-01-01T00:00:30Z').getTime()
import { TaskRunProgressStep, TaskRunStreamState } from './taskRunStreamLogic'

function taskState(overrides: Partial<TaskRunStreamState> = {}): TaskRunStreamState {
    return {
        status: 'in_progress',
        stage: null,
        output: null,
        branch: null,
        error_message: null,
        updated_at: '2026-01-01T00:00:00Z',
        completed_at: null,
        ...overrides,
    }
}

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

function session(overrides: Partial<WizardSessionDTOApi> = {}): WizardSessionDTOApi {
    return {
        session_id: 's',
        team_id: 1,
        workflow_id: 'posthog-integration',
        skill_id: '',
        started_at: '2026-01-01T00:00:00Z',
        run_phase: 'running',
        tasks: [],
        event_plan: null,
        error: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        is_stale: false,
        ...overrides,
    } as unknown as WizardSessionDTOApi
}

describe('installationProgressLogic merge', () => {
    describe('cloudProgress', () => {
        it.each([
            ['no state + idle connection → idle', null, 'idle', 'idle'],
            ['no state + connecting → connecting', null, 'connecting', 'connecting'],
            ['no state + open connection → idle', null, 'open', 'idle'],
            // Queued means nothing has started yet — presenting it as "running" told users the
            // wizard was working when no worker had picked the run up.
            ['queued → connecting', 'queued', 'open', 'connecting'],
            ['in_progress → running', 'in_progress', 'open', 'running'],
            ['completed → completed', 'completed', 'open', 'completed'],
            ['failed → error', 'failed', 'open', 'error'],
            ['cancelled → error', 'cancelled', 'open', 'error'],
        ])('phase: %s', (_name, status, conn, expected) => {
            const state = status === null ? null : taskState({ status })
            expect(cloudProgress(state, [], conn, null).phase).toBe(expected)
        })

        it('surfaces a stalled queued run as an error instead of an eternal spinner', () => {
            const result = cloudProgress(taskState({ status: 'queued' }), [], 'open', null, true)
            expect(result.phase).toBe('error')
            expect(result.error?.title).toBe("Setup hasn't started")
        })

        it('ignores the stall flag once the run has left the queue', () => {
            expect(cloudProgress(taskState({ status: 'in_progress' }), [], 'open', null, true).phase).toBe('running')
        })

        it.each([
            ['pending', 'pending'],
            ['in_progress', 'in_progress'],
            ['completed', 'completed'],
            ['failed', 'failed'],
            ['canceled', 'failed'],
            ['something-else', 'pending'],
        ])('maps backend step status %s → %s', (raw, expected) => {
            const result = cloudProgress(taskState(), [step({ status: raw })], 'open', null)
            expect(result.steps[0].status).toBe(expected)
        })

        it('maps a step to id/label/detail', () => {
            const result = cloudProgress(
                taskState(),
                [step({ group: 'setup', step: 'clone', label: 'Cloning', detail: 'shallow' })],
                'open',
                null
            )
            expect(result.steps[0]).toEqual({
                id: 'setup:clone',
                label: 'Cloning',
                status: 'in_progress',
                detail: 'shallow',
            })
        })

        it('replaces the wizard stage with the session tasks once they exist', () => {
            const result = cloudProgress(
                taskState(),
                [
                    step({ step: 'clone', status: 'completed', label: 'Cloned repository' }),
                    step({ step: 'wizard', status: 'in_progress', label: 'Running setup wizard' }),
                    step({ step: 'pr', status: 'pending', label: 'Opening pull request', group: 'deliver' }),
                ],
                'open',
                session({
                    tasks: [
                        { id: 'a', title: 'Detect framework', status: 'completed' },
                        { id: 'b', title: 'Install SDK', status: 'in_progress' },
                    ],
                }),
                false,
                NOW
            )
            expect(result.steps.map((s) => [s.label, s.status, s.source ?? null])).toEqual([
                ['Cloned repository', 'completed', null],
                ['Detect framework', 'completed', 'wizard'],
                ['Install SDK', 'in_progress', 'wizard'],
                ['Opening pull request', 'pending', null],
            ])
        })

        it('appends session tasks at the end when no wizard stage has been announced', () => {
            const result = cloudProgress(
                taskState(),
                [],
                'open',
                session({ tasks: [{ id: 'a', title: 'Detect framework', status: 'in_progress' }] }),
                false,
                NOW
            )
            expect(result.steps).toEqual([
                {
                    id: 'wizard-task:a',
                    label: 'Detect framework',
                    status: 'in_progress',
                    detail: null,
                    source: 'wizard',
                },
            ])
        })

        it('keeps the timeline bare when there is no session', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'wizard', status: 'in_progress', detail: 'own detail' })],
                'open',
                null
            )
            expect(result.steps).toHaveLength(1)
            expect(result.steps[0].detail).toBe('own detail')
        })

        it('clamps lingering in-progress wizard tasks once the run completes', () => {
            const result = cloudProgress(
                taskState({ status: 'completed' }),
                [step({ step: 'wizard', status: 'completed' })],
                'open',
                session({ tasks: [{ id: 'a', title: 'Install SDK', status: 'in_progress' }] }),
                false,
                NOW
            )
            expect(result.steps).toHaveLength(1)
            expect(result.steps[0]).toMatchObject({ label: 'Install SDK', status: 'completed', source: 'wizard' })
        })

        it('uses the task run error message on failure', () => {
            expect(
                cloudProgress(taskState({ status: 'failed', error_message: 'boom' }), [], 'open', null).error
            ).toEqual({
                title: 'Installation failed',
                detail: 'boom',
            })
        })

        it('falls back to the wizard session error message', () => {
            expect(
                cloudProgress(
                    taskState({ status: 'failed', error_message: null }),
                    [],
                    'open',
                    session({ error: { message: 'wizard boom' } }),
                    false,
                    NOW
                ).error
            ).toEqual({ title: 'Installation failed', detail: 'wizard boom' })
        })

        it('error detail is null when neither source has a message', () => {
            expect(cloudProgress(taskState({ status: 'failed', error_message: null }), [], 'open', null).error).toEqual(
                {
                    title: 'Installation failed',
                    detail: null,
                }
            )
        })

        it('has no error outside an error phase', () => {
            expect(cloudProgress(taskState({ status: 'in_progress' }), [], 'open', null).error).toBeNull()
        })

        it.each([
            [
                'output with pr_url',
                taskState({ status: 'completed', output: { pr_url: 'https://x/pull/1' } }),
                'https://x/pull/1',
            ],
            ['output without pr_url', taskState({ status: 'completed', output: {} }), null],
            ['null output', taskState({ status: 'completed', output: null }), null],
            ['no task state', null, null],
        ])('prUrl: %s', (_name, state, expected) => {
            expect(cloudProgress(state, [], 'open', null).prUrl).toBe(expected)
        })

        it('isCurrent is false only when idle', () => {
            expect(cloudProgress(null, [], 'idle', null).isCurrent).toBe(false)
            expect(cloudProgress(taskState({ status: 'in_progress' }), [], 'open', null).isCurrent).toBe(true)
            expect(cloudProgress(taskState({ status: 'completed' }), [], 'open', null).isCurrent).toBe(true)
        })
    })

    describe('localProgress', () => {
        it.each([
            ['no session + connecting → connecting', null, 'connecting', 'connecting'],
            ['no session + open → idle', null, 'open', 'idle'],
            ['no session + idle → idle', null, 'idle', 'idle'],
            ['completed → completed', { run_phase: 'completed' }, 'open', 'completed'],
            ['error → error', { run_phase: 'error' }, 'open', 'error'],
            ['running + open → running', { run_phase: 'running' }, 'open', 'running'],
            ['running + connecting conn → connecting', { run_phase: 'running' }, 'connecting', 'connecting'],
            ['running + error conn → connecting', { run_phase: 'running' }, 'error', 'connecting'],
        ])('phase: %s', (_name, sessionOverrides, conn, expected) => {
            const s = sessionOverrides === null ? null : session(sessionOverrides as Partial<WizardSessionDTOApi>)
            expect(localProgress(s, conn, true).phase).toBe(expected)
        })

        it('maps session tasks to steps', () => {
            const result = localProgress(
                session({
                    run_phase: 'running',
                    tasks: [
                        { id: 'a', title: 'Detect framework', status: 'completed' },
                        { id: 'b', title: 'Install SDK', status: 'in_progress' },
                    ],
                }),
                'open',
                true
            )
            expect(result.steps).toEqual([
                { id: 'a', label: 'Detect framework', status: 'completed', detail: null },
                { id: 'b', label: 'Install SDK', status: 'in_progress', detail: null },
            ])
        })

        it('surfaces the wizard error on the error phase', () => {
            expect(
                localProgress(session({ run_phase: 'error', error: { message: 'wizard boom' } }), 'open', true).error
            ).toEqual({
                title: 'Wizard hit an error',
                detail: 'wizard boom',
            })
        })

        it('error detail is null when the session has no error message', () => {
            expect(localProgress(session({ run_phase: 'error', error: null }), 'open', true).error).toEqual({
                title: 'Wizard hit an error',
                detail: null,
            })
        })

        it('has no error outside the error phase', () => {
            expect(localProgress(session({ run_phase: 'running' }), 'open', true).error).toBeNull()
        })

        it('never has a pr url', () => {
            expect(localProgress(session({ run_phase: 'completed' }), 'open', true).prUrl).toBeNull()
        })

        it('isCurrent mirrors the sticky freshness flag, never a bare session', () => {
            // A stale terminal row replayed by the SSE on connect must not read as a run in flight —
            // that is what used to hijack the install step before the freshness guard.
            expect(localProgress(null, 'open', true).isCurrent).toBe(false)
            expect(localProgress(session({ run_phase: 'running' }), 'open', false).isCurrent).toBe(false)
            expect(localProgress(session({ run_phase: 'running' }), 'open', true).isCurrent).toBe(true)
        })
    })

    describe('isSessionFresh', () => {
        const NOW = new Date('2026-01-01T00:00:00Z').getTime()
        it.each([
            ['updated just now', '2026-01-01T00:00:00Z', true],
            ['updated 9 minutes ago', '2025-12-31T23:51:00Z', true],
            ['updated 11 minutes ago', '2025-12-31T23:49:00Z', false],
            ['unparseable timestamp', 'not-a-date', false],
        ])('%s → %s', (_name, updatedAt, expected) => {
            expect(isSessionFresh(session({ updated_at: updatedAt }), NOW)).toBe(expected)
        })
    })

    describe('cloudProgress session freshness gate', () => {
        const NOW_MS = new Date('2026-01-01T00:00:30Z').getTime()
        it('ignores a stale session for both the timeline and the error fallback', () => {
            // A stale terminal row replayed on connect must not leak a previous run's tasks or error
            // text into a fresh cloud run.
            const stale = session({
                updated_at: '2025-12-01T00:00:00Z',
                tasks: [{ id: 'a', title: 'Old task', status: 'completed' }],
                error: { message: 'old boom' },
            })
            const running = cloudProgress(taskState(), [], 'open', stale, false, NOW_MS)
            expect(running.steps).toEqual([])
            const failed = cloudProgress(
                taskState({ status: 'failed', error_message: null }),
                [],
                'open',
                stale,
                false,
                NOW_MS
            )
            expect(failed.error?.detail).toBeNull()
        })

        it('inserts wizard tasks before the first unfinished pipeline step when no wizard stage exists', () => {
            const result = cloudProgress(
                taskState(),
                [
                    step({ step: 'clone', status: 'completed', label: 'Cloned repository' }),
                    step({ step: 'pr', status: 'pending', label: 'Opening pull request', group: 'deliver' }),
                ],
                'open',
                session({ tasks: [{ id: 'a', title: 'Install SDK', status: 'in_progress' }] }),
                false,
                NOW_MS
            )
            expect(result.steps.map((s) => s.label)).toEqual([
                'Cloned repository',
                'Install SDK',
                'Opening pull request',
            ])
        })
    })

    describe('runLocalSessionBookkeeping', () => {
        const spyActions = (): {
            markSessionCurrent: jest.Mock
            reportWizardSyncSessionDetected: jest.Mock
            reportWizardSyncSessionFinished: jest.Mock
        } => ({
            markSessionCurrent: jest.fn(),
            reportWizardSyncSessionDetected: jest.fn(),
            reportWizardSyncSessionFinished: jest.fn(),
        })
        const fresh = (overrides: Partial<WizardSessionDTOApi> = {}): WizardSessionDTOApi =>
            session({ updated_at: new Date(Date.now() - 1000).toISOString(), ...overrides })

        beforeEach(() => resetWizardSyncTelemetryForTests())

        it('marks the session current and reports detected once per session across redeliveries', () => {
            const actions = spyActions()
            const s = fresh({ session_id: 'dup' })
            runLocalSessionBookkeeping(s, null, actions)
            runLocalSessionBookkeeping(s, s, actions)
            expect(actions.markSessionCurrent).toHaveBeenCalledTimes(2)
            expect(actions.reportWizardSyncSessionDetected).toHaveBeenCalledTimes(1)
        })

        it('ignores a stale session entirely for freshness and reach telemetry', () => {
            const actions = spyActions()
            runLocalSessionBookkeeping(session({ updated_at: '2020-01-01T00:00:00Z' }), null, actions)
            expect(actions.markSessionCurrent).not.toHaveBeenCalled()
            expect(actions.reportWizardSyncSessionDetected).not.toHaveBeenCalled()
        })

        it('reports finished only on an observed transition into a terminal phase, once', () => {
            const actions = spyActions()
            const running = fresh({ session_id: 'fin', run_phase: 'running' })
            const done = fresh({ session_id: 'fin', run_phase: 'completed' })
            runLocalSessionBookkeeping(done, null, actions) // replayed terminal state: no transition
            expect(actions.reportWizardSyncSessionFinished).not.toHaveBeenCalled()
            runLocalSessionBookkeeping(done, running, actions)
            runLocalSessionBookkeeping(done, running, actions)
            expect(actions.reportWizardSyncSessionFinished).toHaveBeenCalledTimes(1)
        })

        it('tolerates a malformed session with null tasks', () => {
            const actions = spyActions()
            const s = fresh({ session_id: 'null-tasks', tasks: null as unknown as WizardSessionDTOApi['tasks'] })
            expect(() => runLocalSessionBookkeeping(s, null, actions)).not.toThrow()
            expect(actions.reportWizardSyncSessionDetected).toHaveBeenCalledWith(
                expect.objectContaining({ taskCount: 0 })
            )
        })
    })
})
