import { MOCK_DEFAULT_USER, MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { tasksActiveWizardRunRetrieve } from 'products/tasks/frontend/generated/api'

import { activeCloudRunLogic, CloudRunHandle, scopedCloudRun } from './activeCloudRunLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksActiveWizardRunRetrieve: jest.fn(),
}))

const mockActiveWizardRun = tasksActiveWizardRunRetrieve as jest.Mock

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
    })
})
