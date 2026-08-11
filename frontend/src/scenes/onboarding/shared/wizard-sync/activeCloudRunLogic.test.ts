import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'
import type { AppContext, OnboardingSkippedReason, TeamType } from '~/types'

import { tasksActiveWizardRunRetrieve, tasksRunsCancelCreate } from 'products/tasks/frontend/generated/api'

import {
    activeCloudRunLogic,
    CloudRunHandle,
    CloudRunReconciliation,
    RECONCILE_INTERVAL_MS,
    reconcileCloudRun,
    scopedCloudRun,
} from './activeCloudRunLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksActiveWizardRunRetrieve: jest.fn(),
    tasksRunsCancelCreate: jest.fn(),
}))

const mockActiveWizardRun = tasksActiveWizardRunRetrieve as jest.Mock
const mockRunCancel = tasksRunsCancelCreate as jest.Mock

const RUN_STARTED_AT = '2026-01-01T00:00:00Z'

const handle: CloudRunHandle = {
    taskId: 'task-1',
    runId: 'run-1',
    startedAt: '2026-01-01T00:00:00Z',
    projectId: 2,
}

// userLogic reads the bootstrapped user out of the app context, so seeding it there is how a test
// picks which kind of account is looking at the run.
function initAs(onboardingSkippedReason: OnboardingSkippedReason, team: TeamType = MOCK_DEFAULT_TEAM): void {
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        current_user: { ...MOCK_DEFAULT_USER, onboarding_skipped_reason: onboardingSkippedReason },
    } as unknown as AppContext
    initKeaTests(true, team)
}

describe('activeCloudRunLogic', () => {
    describe('scopedCloudRun', () => {
        it.each([
            // The persisted handle is browser-wide localStorage — a fresh account inheriting another
            // project's run must never surface it.
            ['a handle from another project', handle, 7, null],
            ['a legacy handle without a projectId', { ...handle, projectId: undefined }, 2, null],
            ['no current project resolved yet', handle, null, null],
            ['no handle at all', null, 2, null],
            ['a handle for the current project', handle, 2, handle],
        ])('returns %s correctly', (_name, persisted, currentProjectId, expected) => {
            expect(scopedCloudRun(persisted, currentProjectId as number | null)).toEqual(expected)
        })
    })

    describe('reconcileCloudRun', () => {
        const serverRun = { run_id: 'run-2' }
        const cases: [string, CloudRunHandle | null, { run_id: string } | null, boolean, CloudRunReconciliation][] = [
            // 204: the server drops terminal and stale runs, so whatever the client holds is retired.
            // Retiring works for every account, adoption does not.
            ['clears a handle the server no longer reports', handle, null, false, 'clear'],
            ['clears a handle for an adopting client too', handle, null, true, 'clear'],
            ['keeps nothing when there is nothing to clear', null, null, false, 'keep'],
            // The drop-flow signup: the run was started server-side, so this browser never had a handle.
            ['adopts a server run the client never wrote', null, serverRun, true, 'adopt'],
            // The endpoint is team-scoped and names no creator, so an answer to a client that cannot
            // have started a run server-side may well be a teammate's run. Taking it would put their
            // task titles, event plan and errors on this user's screen, behind this user's Cancel.
            ['leaves a team run alone for anyone else', null, serverRun, false, 'keep'],
            // The run's outcome reaches the surfaces through its stream; clearing here would drop the
            // finished-run handoff before the user dismissed it.
            ['keeps a terminal answer for the run it already tracks', handle, { run_id: handle.runId }, true, 'keep'],
            // A held handle is never displaced, not even for the account adoption is open to.
            ['keeps the local handle against a different run the team is running', handle, serverRun, true, 'keep'],
        ]
        it.each(cases)('%s', (_name, local, server, canAdopt, expected) => {
            expect(reconcileCloudRun(local, server, canAdopt)).toBe(expected)
        })
    })

    describe('hydrateFromServer', () => {
        let logic: ReturnType<typeof activeCloudRunLogic.build>

        beforeEach(() => {
            // The handle is persisted to localStorage, so clear it or a seeded run leaks across tests.
            window.localStorage.clear()
            // The app context survives between tests, so reset the user or a provisioned one leaks.
            initAs(null)
            mockActiveWizardRun.mockReset()
            projectLogic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('seeds a run started server-side for the drop-flow signup', async () => {
            // The provisioned signup is the one account whose run is started server-side, so this
            // browser never wrote a handle for it and the server answer is the only way to find it.
            initAs('provisioned', { ...MOCK_DEFAULT_TEAM, completed_snippet_onboarding: false })
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'srv-task',
                run_id: 'srv-run',
                status: 'in_progress',
                started_at: '2026-02-02T00:00:00Z',
            })
            logic = activeCloudRunLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['hydrateFromServer', 'setActiveCloudRun'])
            expect(mockActiveWizardRun).toHaveBeenCalledWith(String(MOCK_TEAM_ID))
            expect(logic.values.activeCloudRun).toMatchObject({
                taskId: 'srv-task',
                runId: 'srv-run',
                projectId: MOCK_TEAM_ID,
            })
        })

        it('never seeds a teammate onto the team run', async () => {
            // The endpoint is team-scoped and names no creator, so a member who joined mid-onboarding
            // would otherwise take over whatever the team is running: its task titles, event plan and
            // errors on their screen, and their Cancel button pointed at it.
            initAs(null, { ...MOCK_DEFAULT_TEAM, completed_snippet_onboarding: false })
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'srv-task',
                run_id: 'srv-run',
                status: 'in_progress',
                started_at: '2026-02-02T00:00:00Z',
            })
            logic = activeCloudRunLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeCloudRun).toBeNull()
            // Nothing this member can do with the answer, so it does not cost a request either.
            expect(mockActiveWizardRun).not.toHaveBeenCalled()
        })

        it('spends no request on mount for a finished-onboarding team holding no handle', async () => {
            // This logic is mounted app-wide, so without the gate every authenticated pageload in the
            // product would cost one request to an endpoint that can only answer "nothing here".
            mockActiveWizardRun.mockResolvedValue(undefined)
            logic = activeCloudRunLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(mockActiveWizardRun).not.toHaveBeenCalled()
        })

        it('reconciles a handle held by a team that already finished onboarding', async () => {
            // The gate is about what a request can achieve, not about who the user is: a handle
            // always needs checking, whatever the team's onboarding state.
            mockActiveWizardRun.mockResolvedValue(undefined)
            logic = activeCloudRunLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(mockActiveWizardRun).not.toHaveBeenCalled()

            logic.actions.setActiveCloudRun('task-1', 'run-1', RUN_STARTED_AT, MOCK_TEAM_ID)

            await expectLogic(logic).toDispatchActions(['hydrateFromServer', 'clearActiveCloudRun'])
        })

        it('reconciles again when the tab becomes visible, while a handle is held', async () => {
            // Confirming the same run keeps the handle in place, so the second trigger has something
            // to check.
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'task-1',
                run_id: 'run-1',
                status: 'in_progress',
                started_at: RUN_STARTED_AT,
            })
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('task-1', 'run-1', RUN_STARTED_AT, MOCK_TEAM_ID)
            await expectLogic(logic).toDispatchActions(['hydrateFromServer'])
            const callsAfterMount = mockActiveWizardRun.mock.calls.length

            document.dispatchEvent(new Event('visibilitychange'))

            await expectLogic(logic).toDispatchActions(['hydrateFromServer'])
            expect(mockActiveWizardRun.mock.calls.length).toBe(callsAfterMount + 1)
        })

        it('spends no request on tab focus without a handle', async () => {
            mockActiveWizardRun.mockResolvedValue(undefined)
            logic = activeCloudRunLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            document.dispatchEvent(new Event('visibilitychange'))
            await expectLogic(logic).toFinishAllListeners()

            expect(mockActiveWizardRun).not.toHaveBeenCalled()
        })

        it('reconciles on the interval only while a handle is held', () => {
            jest.useFakeTimers()
            try {
                // Confirming the same run keeps the handle, so the interval has something to check.
                mockActiveWizardRun.mockResolvedValue({
                    task_id: 'task-1',
                    run_id: 'run-1',
                    status: 'in_progress',
                    started_at: RUN_STARTED_AT,
                })
                logic = activeCloudRunLogic()
                logic.mount()
                const callsAfterMount = mockActiveWizardRun.mock.calls.length

                // No handle: nothing to retire, so the tick must not spend a request.
                jest.advanceTimersByTime(RECONCILE_INTERVAL_MS)
                expect(mockActiveWizardRun.mock.calls.length).toBe(callsAfterMount)

                logic.actions.setActiveCloudRun('task-1', 'run-1', RUN_STARTED_AT, MOCK_TEAM_ID)
                const callsWithHandle = mockActiveWizardRun.mock.calls.length
                jest.advanceTimersByTime(RECONCILE_INTERVAL_MS)
                expect(mockActiveWizardRun.mock.calls.length).toBe(callsWithHandle + 1)
            } finally {
                jest.useRealTimers()
            }
        })

        it('does not swap a held handle for another run the team is running', async () => {
            // The endpoint answers with the newest onboarding run in the project, whoever started it,
            // so a teammate's run must not take over this user's surfaces (or their Cancel button).
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'srv-task',
                run_id: 'srv-run',
                status: 'in_progress',
                started_at: '2026-04-04T00:00:00Z',
            })
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('local-task', 'local-run', '2026-03-03T00:00:00Z', MOCK_TEAM_ID)

            logic.actions.hydrateFromServer()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.activeCloudRun).toMatchObject({ taskId: 'local-task' })
        })

        it('cancels the active run and recovers the button once the request settles', async () => {
            // Server-side hydration confirms the same run, so it must not clear the local handle mid-test.
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'task-1',
                run_id: 'run-1',
                status: 'in_progress',
                started_at: '2026-01-01T00:00:00Z',
            })
            mockRunCancel.mockResolvedValue({ id: 'run-1', status: 'cancelled' })
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('task-1', 'run-1', '2026-01-01T00:00:00Z', MOCK_TEAM_ID)

            logic.actions.cancelActiveCloudRun()
            expect(logic.values.cancellingRun).toBe(true)
            await expectLogic(logic).toDispatchActions(['cancelActiveCloudRun', 'cancelActiveCloudRunSuccess'])

            expect(mockRunCancel).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'task-1', 'run-1')
            // The handle stays: the run stream delivers the terminal status, and the user dismisses
            // the finished run as usual. Cancelling resets so a dead stream can't strand a
            // permanently disabled button (a repeat cancel is idempotent server-side).
            expect(logic.values.activeCloudRun).not.toBeNull()
            expect(logic.values.cancellingRun).toBe(false)
        })

        it('recovers the cancel button when the cancel request fails', async () => {
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'task-1',
                run_id: 'run-1',
                status: 'in_progress',
                started_at: '2026-01-01T00:00:00Z',
            })
            mockRunCancel.mockRejectedValue(new Error('temporal unavailable'))
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('task-1', 'run-1', '2026-01-01T00:00:00Z', MOCK_TEAM_ID)

            logic.actions.cancelActiveCloudRun()
            await expectLogic(logic).toDispatchActions(['cancelActiveCloudRun', 'cancelActiveCloudRunFailure'])

            // A failed cancel must not strand the button in a loading state or drop the run.
            expect(logic.values.cancellingRun).toBe(false)
            expect(logic.values.activeCloudRun).not.toBeNull()
        })

        it('resets an in-flight cancelling state when a new run handle is set', () => {
            // The flag belongs to the run it was set for; a new run (startCloudRun or server
            // hydration) must start with a usable Cancel button, not one disabled by the old run.
            mockActiveWizardRun.mockResolvedValue(undefined)
            mockRunCancel.mockReturnValue(new Promise(() => {}))
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('task-1', 'run-1', '2026-01-01T00:00:00Z', MOCK_TEAM_ID)
            logic.actions.cancelActiveCloudRun()
            expect(logic.values.cancellingRun).toBe(true)

            logic.actions.setActiveCloudRun('task-2', 'run-2', '2026-01-02T00:00:00Z', MOCK_TEAM_ID)

            expect(logic.values.cancellingRun).toBe(false)
        })

        it('does not call the cancel endpoint without an active handle', async () => {
            mockActiveWizardRun.mockResolvedValue(undefined)
            logic = activeCloudRunLogic()
            logic.mount()

            logic.actions.cancelActiveCloudRun()
            await expectLogic(logic).toDispatchActions(['cancelActiveCloudRun', 'cancelActiveCloudRunFailure'])

            expect(mockRunCancel).not.toHaveBeenCalled()
        })

        it('clears a stale local handle when the server reports no active run', async () => {
            // A returning user whose run finished or was abandoned still has a handle in localStorage.
            // Reconciliation must retire it, or the install card and FAB keep claiming setup is in
            // flight forever.
            mockActiveWizardRun.mockResolvedValue(undefined)
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('stale-task', 'stale-run', '2026-01-01T00:00:00Z', MOCK_TEAM_ID)
            expect(logic.values.activeCloudRun).not.toBeNull()

            logic.actions.hydrateFromServer()

            await expectLogic(logic).toDispatchActions(['hydrateFromServer', 'clearActiveCloudRun'])
            expect(logic.values.activeCloudRun).toBeNull()
        })

        it('does not let an answer about an older run retire the one just started', async () => {
            // A kickoff can land while a reconcile is in flight. That answer was computed before the
            // new run existed, so applying its 204 would clear a run that is only just starting.
            let answer: (value: unknown) => void = () => {}
            mockActiveWizardRun.mockReturnValue(
                new Promise((resolve) => {
                    answer = resolve
                })
            )
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('old-task', 'old-run', '2026-01-01T00:00:00Z', MOCK_TEAM_ID)
            logic.actions.hydrateFromServer()

            logic.actions.setActiveCloudRun('new-task', 'new-run', '2026-01-02T00:00:00Z', MOCK_TEAM_ID)
            answer(undefined)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.activeCloudRun).toMatchObject({ taskId: 'new-task', runId: 'new-run' })
        })
    })
})
