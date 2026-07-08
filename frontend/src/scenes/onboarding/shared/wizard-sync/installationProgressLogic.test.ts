import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import type { FinishedLocalRunHandle } from './finishedLocalRunLogic'
import {
    cloudProgress,
    isSessionFresh,
    localProgress,
    progressFromFinishedLocalRun,
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
            expect(result.steps.find((s) => s.id === 'setup:clone')?.status).toBe(expected)
        })

        it('maps a step to id/label/detail', () => {
            const result = cloudProgress(
                taskState(),
                [step({ group: 'setup', step: 'clone', label: 'Cloning', detail: 'shallow' })],
                'open',
                null
            )
            expect(result.steps.find((s) => s.id === 'setup:clone')).toEqual({
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
                ['Setting up sandbox', 'pending', null],
                ['Cloned repository', 'completed', null],
                ['Detect framework', 'completed', 'wizard'],
                ['Install SDK', 'in_progress', 'wizard'],
                ['Opening pull request', 'pending', null],
            ])
        })

        it('slots session tasks into the skeleton wizard slot before any stage is announced', () => {
            const result = cloudProgress(
                taskState(),
                [],
                'open',
                session({ tasks: [{ id: 'a', title: 'Detect framework', status: 'in_progress' }] }),
                false,
                NOW
            )
            expect(result.steps.map((s) => [s.label, s.status, s.source ?? null])).toEqual([
                ['Setting up sandbox', 'pending', null],
                ['Cloning repository', 'pending', null],
                ['Detect framework', 'in_progress', 'wizard'],
                ['Opening a pull request', 'pending', null],
            ])
        })

        it('keeps the announced wizard stage when there is no session', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'wizard', status: 'in_progress', detail: 'own detail' })],
                'open',
                null
            )
            expect(result.steps.find((s) => s.id === 'setup:wizard')?.detail).toBe('own detail')
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
            expect(result.steps.find((s) => s.source === 'wizard')).toMatchObject({
                label: 'Install SDK',
                status: 'completed',
            })
            expect(result.steps.find((s) => s.id === 'setup:wizard')).toBeUndefined()
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

        it('a dismissed session is not current even while fresh', () => {
            // Dismissal must release the install-step takeover immediately — the sticky freshness
            // flag alone would keep the completed panel pinned until the next remount.
            expect(localProgress(session({ run_phase: 'completed' }), 'open', true, true).isCurrent).toBe(false)
        })
    })

    describe('progressFromFinishedLocalRun', () => {
        const handle = (overrides: Partial<FinishedLocalRunHandle> = {}): FinishedLocalRunHandle => ({
            sessionId: 's',
            projectId: 1,
            startedAt: '2026-01-01T00:00:00Z',
            finishedAt: '2026-01-01T00:05:00Z',
            runPhase: 'completed',
            tasks: [
                { id: 'a', title: 'Detect framework', status: 'completed' },
                { id: 'b', title: 'Install SDK', status: 'canceled' },
            ],
            error: null,
            ...overrides,
        })

        it('renders the snapshot like the live path rendered the same terminal session', () => {
            // The FAB switches from the live stream to this snapshot when the stream gates itself
            // off — a mapping drift would make the card visibly rewrite itself at that moment.
            expect(progressFromFinishedLocalRun(handle())).toEqual({
                phase: 'completed',
                steps: [
                    { id: 'a', label: 'Detect framework', status: 'completed', detail: null },
                    { id: 'b', label: 'Install SDK', status: 'failed', detail: null },
                ],
                error: null,
                prUrl: null,
                isCurrent: true,
                isSlow: false,
            })
        })

        it('surfaces the persisted error on failed runs', () => {
            const result = progressFromFinishedLocalRun(handle({ runPhase: 'error', error: { message: 'boom' } }))
            expect(result.phase).toBe('error')
            expect(result.error).toEqual({ title: 'Wizard hit an error', detail: 'boom' })
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

    describe('cloudProgress agent-gap bridging', () => {
        const NOW_MS = new Date('2026-01-01T00:00:30Z').getTime()
        it('flips the pending PR slot to in-progress and hides the agent plumbing row', () => {
            // The quiet window between agent start and the PR opening must not read as stalled,
            // and 'Started agent' is internal plumbing the user shouldn't see at all.
            const result = cloudProgress(
                taskState(),
                [
                    step({ step: 'sandbox', status: 'completed', label: 'Set up sandbox' }),
                    step({ step: 'clone', status: 'completed', label: 'Cloned repository' }),
                    step({ step: 'wizard', status: 'completed', label: 'Ran setup wizard' }),
                    step({ step: 'agent', status: 'completed', label: 'Started agent' }),
                ],
                'open',
                null
            )
            expect(result.steps.map((s) => [s.label, s.status])).toEqual([
                ['Set up sandbox', 'completed'],
                ['Cloned repository', 'completed'],
                ['Ran setup wizard', 'completed'],
                ['Opening a pull request', 'in_progress'],
            ])
        })

        it.each([
            ['a step is still in flight', [step({ step: 'wizard', status: 'in_progress' })], null],
            [
                'a deliver-stage step already exists',
                [
                    step({ step: 'agent', status: 'completed' }),
                    step({ step: 'pr', status: 'completed', group: 'deliver', detail: 'https://x/pull/1' }),
                ],
                null,
            ],
            ['the run has completed', [step({ step: 'agent', status: 'completed' })], 'completed'],
        ])('does not synthesize when %s', (_name, progressSteps, status) => {
            const result = cloudProgress(
                taskState(status ? { status } : {}),
                progressSteps as TaskRunProgressStep[],
                'open',
                null,
                false,
                false,
                NOW_MS
            )
            expect(result.steps.find((s) => s.id.endsWith(':pr'))?.status ?? 'pending').not.toBe('in_progress')
        })

        const bridgedSteps = [
            step({ step: 'sandbox', status: 'completed', label: 'Set up sandbox' }),
            step({ step: 'clone', status: 'completed', label: 'Cloned repository' }),
            step({ step: 'wizard', status: 'completed', label: 'Ran setup wizard' }),
            step({ step: 'agent', status: 'completed', label: 'Started agent' }),
        ]

        it('narrates the synthetic PR-drafting message while activity is recent', () => {
            const result = cloudProgress(taskState(), bridgedSteps, 'open', null, false, false)
            expect(result.isSlow).toBe(false)
            expect(result.steps.find((s) => s.id.endsWith(':pr'))?.detail).toBe(
                'The agent is committing its changes and drafting the PR'
            )
        })

        it('flags a long-silent run as slow with an honest message instead of the fake one', () => {
            // The regression: a wedged run would show "drafting the PR" forever with no way out.
            const result = cloudProgress(taskState(), bridgedSteps, 'open', null, false, true)
            expect(result.isSlow).toBe(true)
            expect(result.steps.find((s) => s.id.endsWith(':pr'))?.detail).toBe('This is taking longer than expected')
        })

        it('is not slow once a PR exists, even after a silence', () => {
            const result = cloudProgress(
                taskState(),
                [step({ step: 'pr', status: 'completed', group: 'deliver', detail: 'https://x/pull/1' })],
                'open',
                null,
                false,
                true
            )
            expect(result.isSlow).toBe(false)
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
            const running = cloudProgress(taskState(), [], 'open', stale, false, false, NOW_MS)
            expect(running.steps.filter((s) => s.source === 'wizard')).toEqual([])
            const failed = cloudProgress(
                taskState({ status: 'failed', error_message: null }),
                [],
                'open',
                stale,
                false,
                false,
                NOW_MS
            )
            expect(failed.error?.detail).toBeNull()
        })

        it('replaces the skeleton wizard slot with wizard tasks', () => {
            const result = cloudProgress(
                taskState(),
                [
                    step({ step: 'clone', status: 'completed', label: 'Cloned repository' }),
                    step({ step: 'pr', status: 'pending', label: 'Opening pull request', group: 'deliver' }),
                ],
                'open',
                session({ tasks: [{ id: 'a', title: 'Install SDK', status: 'in_progress' }] }),
                false,
                false,
                NOW_MS
            )
            expect(result.steps.map((s) => s.label)).toEqual([
                'Setting up sandbox',
                'Cloned repository',
                'Install SDK',
                'Opening pull request',
            ])
        })
    })

    describe('runLocalSessionBookkeeping', () => {
        const spyActions = (): {
            markSessionCurrent: jest.Mock
            recordFinishedLocalRun: jest.Mock
            supersedeFinishedLocalRun: jest.Mock
            reportWizardSyncSessionDetected: jest.Mock
            reportWizardSyncSessionFinished: jest.Mock
        } => ({
            markSessionCurrent: jest.fn(),
            recordFinishedLocalRun: jest.fn(),
            supersedeFinishedLocalRun: jest.fn(),
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

        it.each([
            // Recording must fire on every fresh terminal delivery (a replayed terminal state after
            // a remount is exactly when the FAB needs its snapshot back), never on stale ones —
            // otherwise a finished run's handoff vanishes with the stream, or a stale row from a
            // previous run resurrects a surface the user never watched.
            ['fresh completed session', { run_phase: 'completed' }, true, true],
            ['fresh errored session', { run_phase: 'error' }, true, true],
            ['fresh running session', { run_phase: 'running' }, true, false],
            ['stale completed session', { run_phase: 'completed', updated_at: '2020-01-01T00:00:00Z' }, false, false],
        ])('records the finished-run handle for a %s: %s', (_name, overrides, isFresh, expectRecorded) => {
            const actions = spyActions()
            const s = isFresh
                ? fresh(overrides as Partial<WizardSessionDTOApi>)
                : session(overrides as Partial<WizardSessionDTOApi>)
            runLocalSessionBookkeeping(s, null, actions)
            expect(actions.recordFinishedLocalRun).toHaveBeenCalledTimes(expectRecorded ? 1 : 0)
        })

        it('supersedes the previous finished run when a fresh run goes live', () => {
            // Starting over must replace the old handoff with the live run — otherwise dismissing
            // requires clearing two surfaces, or the old completed card reappears mid-new-run.
            const actions = spyActions()
            runLocalSessionBookkeeping(fresh({ session_id: 'new-run', run_phase: 'running' }), null, actions)
            expect(actions.supersedeFinishedLocalRun).toHaveBeenCalledWith('new-run')
            expect(actions.recordFinishedLocalRun).not.toHaveBeenCalled()
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
