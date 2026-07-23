import { MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { tasksActiveWizardRunRetrieve, tasksRunsCancelCreate } from 'products/tasks/frontend/generated/api'

import { activeCloudRunLogic, CloudRunHandle, scopedCloudRun } from './activeCloudRunLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksActiveWizardRunRetrieve: jest.fn(),
    tasksRunsCancelCreate: jest.fn(),
}))

const mockActiveWizardRun = tasksActiveWizardRunRetrieve as jest.Mock
const mockRunCancel = tasksRunsCancelCreate as jest.Mock

const handle: CloudRunHandle = {
    taskId: 'task-1',
    runId: 'run-1',
    startedAt: '2026-01-01T00:00:00Z',
    projectId: 2,
}

function setUser(provisioned: boolean): void {
    userLogic.mount()
    userLogic.actions.loadUserSuccess({
        ...MOCK_DEFAULT_USER,
        onboarding_skipped_reason: provisioned ? 'provisioned' : null,
    })
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

    describe('hydrateFromServer', () => {
        let logic: ReturnType<typeof activeCloudRunLogic.build>

        beforeEach(() => {
            // The handle is persisted to localStorage, so clear it or a seeded run leaks across tests.
            window.localStorage.clear()
            initKeaTests()
            mockActiveWizardRun.mockReset()
            projectLogic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('seeds the handle for a provisioned user when the server reports an active run', async () => {
            setUser(true)
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

        it('does not call the server for a non-provisioned user', () => {
            setUser(false)
            logic = activeCloudRunLogic()
            logic.mount()

            // Gated before the request — a non-provisioned user never reaches server hydration.
            expect(mockActiveWizardRun).not.toHaveBeenCalled()
            expect(logic.values.activeCloudRun).toBeNull()
        })

        it('hydrates once the provisioned status loads after mount', async () => {
            // The user (and so isProvisionedUser) resolves asynchronously; mounting before it does
            // must not permanently skip the one server lookup — the original one-shot afterMount did.
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'srv-task',
                run_id: 'srv-run',
                status: 'in_progress',
                started_at: '2026-02-02T00:00:00Z',
            })
            logic = activeCloudRunLogic()
            logic.mount()
            expect(mockActiveWizardRun).not.toHaveBeenCalled()

            setUser(true)

            await expectLogic(logic).toDispatchActions(['hydrateFromServer', 'setActiveCloudRun'])
            expect(mockActiveWizardRun).toHaveBeenCalledWith(String(MOCK_TEAM_ID))
            expect(logic.values.activeCloudRun).toMatchObject({ taskId: 'srv-task', runId: 'srv-run' })
        })

        it('does not clobber a fresher local handle', async () => {
            setUser(true)
            // Even if the server reports a run, a local handle already present must win.
            mockActiveWizardRun.mockResolvedValue({
                task_id: 'srv-task',
                run_id: 'srv-run',
                status: 'in_progress',
                started_at: null,
            })
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('local-task', 'local-run', '2026-03-03T00:00:00Z', MOCK_TEAM_ID)

            logic.actions.hydrateFromServer()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.activeCloudRun).toMatchObject({ taskId: 'local-task' })
        })

        it('cancels the active run and recovers the button once the request settles', async () => {
            setUser(true)
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
            setUser(true)
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
            setUser(true)
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
            setUser(true)
            mockActiveWizardRun.mockResolvedValue(undefined)
            logic = activeCloudRunLogic()
            logic.mount()

            logic.actions.cancelActiveCloudRun()
            await expectLogic(logic).toDispatchActions(['cancelActiveCloudRun', 'cancelActiveCloudRunFailure'])

            expect(mockRunCancel).not.toHaveBeenCalled()
        })

        it('clears a stale local handle when the server reports no active run', async () => {
            // A returning provisioned user whose run finished/was abandoned still has a handle in
            // localStorage. Hydration must reconcile it away, or the install card and FAB keep
            // claiming setup is in flight forever. Mount before the user loads so the seeded handle
            // is in place before the single hydration runs (no mount-time race to reason about).
            mockActiveWizardRun.mockResolvedValue(undefined)
            logic = activeCloudRunLogic()
            logic.mount()
            logic.actions.setActiveCloudRun('stale-task', 'stale-run', '2026-01-01T00:00:00Z', MOCK_TEAM_ID)
            expect(logic.values.activeCloudRun).not.toBeNull()

            setUser(true)

            await expectLogic(logic).toDispatchActions(['hydrateFromServer', 'clearActiveCloudRun'])
            expect(logic.values.activeCloudRun).toBeNull()
        })
    })
})
