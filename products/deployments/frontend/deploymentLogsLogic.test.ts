import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { deploymentLogsLogic } from './deploymentLogsLogic'
import { DeploymentStatusEnumApi } from './fixtures'
import type { DeploymentLogsResponseApi } from './generated/api.schemas'

const PROJECT_ID = 'project-1'
const DEPLOYMENT_ID = 'dep-1'

const baseResponse: DeploymentLogsResponseApi = {
    results: [
        {
            timestamp: '2026-05-14T18:10:00.123Z',
            level: 'info',
            step: 'clone',
            line: 'Cloning repo…',
            exit_code: null,
        },
        {
            timestamp: '2026-05-14T18:10:01.456Z',
            level: 'warn',
            step: 'install',
            line: 'WARN deprecated foo@1',
            exit_code: null,
        },
        {
            timestamp: '2026-05-14T18:10:02.789Z',
            level: 'error',
            step: 'build',
            line: 'ERROR: EROFS',
            exit_code: 1,
        },
    ],
    has_more: false,
    row_limit: 1000,
}

describe('deploymentLogsLogic', () => {
    let getCallCount = 0
    let nextResponses: DeploymentLogsResponseApi[]
    let shouldFail = false

    const mountLogic = (
        status: (typeof DeploymentStatusEnumApi)[keyof typeof DeploymentStatusEnumApi]
    ): ReturnType<typeof deploymentLogsLogic.build> => {
        const logic = deploymentLogsLogic({ projectId: PROJECT_ID, deploymentId: DEPLOYMENT_ID, status })
        logic.mount()
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        getCallCount = 0
        nextResponses = [baseResponse]
        shouldFail = false

        useMocks({
            get: {
                '/api/projects/:team/deployment_projects/:project_id/deployments/:id/logs/': () => {
                    getCallCount += 1
                    if (shouldFail) {
                        return [502, { detail: 'HogQL failed' }]
                    }
                    const idx = Math.min(getCallCount - 1, nextResponses.length - 1)
                    return [200, nextResponses[idx]]
                },
            },
        })

        // teamLogic.values.currentTeamId is wired up by initKeaTests; nothing
        // extra needed here.
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('fetches logs once on mount and stores the response', async () => {
        const logic = mountLogic(DeploymentStatusEnumApi.Ready)
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.rawRows).toHaveLength(3)
            expect(logic.values.hasMore).toBe(false)
            expect(logic.values.rowLimit).toBe(1000)
            expect(getCallCount).toBe(1)
        } finally {
            logic.unmount()
        }
    })

    it('schedules a follow-up poll on success while status is non-terminal', async () => {
        const logic = mountLogic(DeploymentStatusEnumApi.Building)
        try {
            // toDispatchActions tolerates intermediate ones (markLogsFetched);
            // we only care that schedulePoll fires after a successful load.
            await expectLogic(logic).toDispatchActions(['loadLogsSuccess', 'schedulePoll'])
        } finally {
            logic.unmount()
        }
    })

    it('does not schedule a follow-up poll when status is terminal', async () => {
        const logic = mountLogic(DeploymentStatusEnumApi.Ready)
        try {
            await expectLogic(logic).toDispatchActions(['loadLogsSuccess'])
            // schedulePoll should NOT fire on a terminal-status mount.
            await expectLogic(logic).toNotHaveDispatchedActions(['schedulePoll'])
        } finally {
            logic.unmount()
        }
    })

    it('does one final fetch and cancels polling when status flips to terminal', async () => {
        const logic = deploymentLogsLogic({
            projectId: PROJECT_ID,
            deploymentId: DEPLOYMENT_ID,
            status: DeploymentStatusEnumApi.Building,
        })
        logic.mount()
        try {
            // Initial poll lifecycle while live.
            await expectLogic(logic).toDispatchActions(['loadLogsSuccess', 'schedulePoll'])
            expect(getCallCount).toBe(1)

            // Re-build the logic with new props — kea fires propsChanged.
            deploymentLogsLogic({
                projectId: PROJECT_ID,
                deploymentId: DEPLOYMENT_ID,
                status: DeploymentStatusEnumApi.Ready,
            })

            // The terminal transition cancels the queued poll and refires loadLogs
            // once so any late lines are picked up.
            await expectLogic(logic).toDispatchActions(['cancelPoll', 'loadLogs', 'loadLogsSuccess'])
            expect(getCallCount).toBe(2)
        } finally {
            logic.unmount()
        }
    })

    it('filters rows by level, step, and search (composed)', async () => {
        const logic = mountLogic(DeploymentStatusEnumApi.Ready)
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.filteredRows).toHaveLength(3)

            logic.actions.toggleLevelFilter('error')
            expect(logic.values.filteredRows).toHaveLength(1)
            expect(logic.values.filteredRows[0].level).toBe('error')

            logic.actions.toggleLevelFilter('error') // toggle off
            logic.actions.toggleStepFilter('install')
            expect(logic.values.filteredRows).toHaveLength(1)
            expect(logic.values.filteredRows[0].step).toBe('install')

            logic.actions.toggleStepFilter('install') // toggle off
            logic.actions.setSearch('EROFS')
            // setSearch debounces, but the filter selector reads `search`
            // directly from the reducer state, so the filtered list updates
            // synchronously — the debounce only delays the listener.
            expect(logic.values.filteredRows).toHaveLength(1)
            expect(logic.values.filteredRows[0].line).toContain('EROFS')
        } finally {
            logic.unmount()
        }
    })

    it('clearFilters wipes level, step, and search filters', async () => {
        const logic = mountLogic(DeploymentStatusEnumApi.Ready)
        try {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.toggleLevelFilter('error')
            logic.actions.toggleStepFilter('build')
            logic.actions.setSearch('something')

            logic.actions.clearFilters()
            expect(logic.values.levelFilters.size).toBe(0)
            expect(logic.values.stepFilters.size).toBe(0)
            expect(logic.values.search).toBe('')
            expect(logic.values.filteredRows).toHaveLength(3)
        } finally {
            logic.unmount()
        }
    })

    it('exposes has_more=true via the selector', async () => {
        nextResponses = [{ ...baseResponse, has_more: true }]
        const logic = mountLogic(DeploymentStatusEnumApi.Ready)
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.hasMore).toBe(true)
        } finally {
            logic.unmount()
        }
    })

    it('on 502, sets logsError and cancels polling (no schedulePoll fires)', async () => {
        shouldFail = true
        // The kea-loaders onFailure hook console.errors uncaught loader errors
        // by design; suppress for this test so the expected 502 doesn't add noise.
        const errSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined)
        const logic = mountLogic(DeploymentStatusEnumApi.Building)
        try {
            await expectLogic(logic).toDispatchActions(['loadLogsFailure', 'cancelPoll'])
            expect(logic.values.logsError).toBe(true)
            expect(getCallCount).toBe(1)
            await expectLogic(logic).toNotHaveDispatchedActions(['schedulePoll'])
        } finally {
            logic.unmount()
            errSpy.mockRestore()
        }
    })

    it('followTail defaults to true while live, false on terminal status', async () => {
        const live = mountLogic(DeploymentStatusEnumApi.Building)
        try {
            await expectLogic(live).toFinishAllListeners()
            expect(live.values.followTail).toBe(true)
        } finally {
            live.unmount()
        }

        const done = mountLogic(DeploymentStatusEnumApi.Ready)
        try {
            await expectLogic(done).toFinishAllListeners()
            expect(done.values.followTail).toBe(false)
        } finally {
            done.unmount()
        }
    })

    it('explicit setFollowTail override survives a status change', async () => {
        const logic = mountLogic(DeploymentStatusEnumApi.Building)
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.followTail).toBe(true)
            logic.actions.setFollowTail(false)
            expect(logic.values.followTail).toBe(false)
        } finally {
            logic.unmount()
        }
    })
})
