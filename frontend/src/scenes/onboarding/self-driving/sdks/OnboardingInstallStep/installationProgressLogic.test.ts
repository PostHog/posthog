import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import { cloudProgress, localProgress } from './installationProgressLogic'
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

        it('enriches an in-progress wizard step with the session in-progress task title', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'wizard', status: 'in_progress', detail: null })],
                'open',
                session({ tasks: [{ id: 't', title: 'Installing SDK', status: 'in_progress' }] })
            )
            expect(result.steps[0].detail).toBe('Installing SDK')
        })

        it('enriches an in-progress wizard step with the wizard error when the session errored', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'wizard', status: 'in_progress', detail: null })],
                'open',
                session({ run_phase: 'error', tasks: [] })
            )
            expect(result.steps[0].detail).toBe('Wizard hit an error')
        })

        it('leaves the wizard step detail alone when there is no session', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'wizard', status: 'in_progress', detail: 'own detail' })],
                'open',
                null
            )
            expect(result.steps[0].detail).toBe('own detail')
        })

        it('does not enrich a non-wizard step', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'clone', status: 'in_progress', detail: 'shallow' })],
                'open',
                session({ tasks: [{ id: 't', title: 'Installing SDK', status: 'in_progress' }] })
            )
            expect(result.steps[0].detail).toBe('shallow')
        })

        it('does not enrich a completed wizard step', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'wizard', status: 'completed', detail: 'own detail' })],
                'open',
                session({ tasks: [{ id: 't', title: 'Installing SDK', status: 'in_progress' }] })
            )
            expect(result.steps[0].detail).toBe('own detail')
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
                    session({ error: { message: 'wizard boom' } })
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
            expect(localProgress(s, conn).phase).toBe(expected)
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
                'open'
            )
            expect(result.steps).toEqual([
                { id: 'a', label: 'Detect framework', status: 'completed', detail: null },
                { id: 'b', label: 'Install SDK', status: 'in_progress', detail: null },
            ])
        })

        it('surfaces the wizard error on the error phase', () => {
            expect(
                localProgress(session({ run_phase: 'error', error: { message: 'wizard boom' } }), 'open').error
            ).toEqual({
                title: 'Wizard hit an error',
                detail: 'wizard boom',
            })
        })

        it('error detail is null when the session has no error message', () => {
            expect(localProgress(session({ run_phase: 'error', error: null }), 'open').error).toEqual({
                title: 'Wizard hit an error',
                detail: null,
            })
        })

        it('has no error outside the error phase', () => {
            expect(localProgress(session({ run_phase: 'running' }), 'open').error).toBeNull()
        })

        it('never has a pr url', () => {
            expect(localProgress(session({ run_phase: 'completed' }), 'open').prUrl).toBeNull()
        })

        it('isCurrent is false only when idle', () => {
            expect(localProgress(null, 'open').isCurrent).toBe(false)
            expect(localProgress(session({ run_phase: 'running' }), 'open').isCurrent).toBe(true)
        })
    })
})
