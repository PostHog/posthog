import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import {
    agenticTestsActivateCreate,
    agenticTestsDestroy,
    agenticTestsList,
    agenticTestsPauseCreate,
    agenticTestsRejectCreate,
    agenticTestsRunNowCreate,
} from '../../generated/api'
import { AgenticTestApi, AgenticTestStatusEnumApi } from '../../generated/api.schemas'

export type AgenticTest = AgenticTestApi
export type AgenticTestStatus = AgenticTestStatusEnumApi
import type { agenticTestsSceneLogicType } from './agenticTestsSceneLogicType'

export type StatusFilter = 'all' | 'active' | 'paused' | 'rejected'

const STATUS_ORDER: Record<AgenticTestStatus, number> = {
    active: 0,
    paused: 1,
    proposed: 2,
    rejected: 3,
}

const projectId = (): string => String(getCurrentTeamId())

export const agenticTestsSceneLogic = kea<agenticTestsSceneLogicType>([
    path(['products', 'agentic_tests', 'frontend', 'scenes', 'AgenticTestsScene', 'agenticTestsSceneLogic']),
    actions({
        deleteTest: (id: string) => ({ id }),
        runNow: (id: string) => ({ id }),
        activateTest: (id: string) => ({ id }),
        pauseTest: (id: string) => ({ id }),
        rejectTest: (id: string) => ({ id }),
        setSearchTerm: (search: string) => ({ search }),
        setStatusFilter: (status: StatusFilter) => ({ status }),
    }),
    reducers({
        searchTerm: ['' as string, { setSearchTerm: (_, { search }) => search }],
        statusFilter: ['all' as StatusFilter, { setStatusFilter: (_, { status }) => status }],
    }),
    loaders({
        tests: [
            [] as AgenticTest[],
            {
                loadTests: async () => {
                    const response = await agenticTestsList(projectId())
                    return [...response.results]
                },
            },
        ],
    }),
    listeners(({ actions }) => ({
        deleteTest: async ({ id }) => {
            await agenticTestsDestroy(projectId(), id)
            actions.loadTests()
        },
        runNow: async ({ id }) => {
            await agenticTestsRunNowCreate(projectId(), id)
            actions.loadTests()
        },
        activateTest: async ({ id }) => {
            await agenticTestsActivateCreate(projectId(), id)
            actions.loadTests()
        },
        pauseTest: async ({ id }) => {
            await agenticTestsPauseCreate(projectId(), id)
            actions.loadTests()
        },
        rejectTest: async ({ id }) => {
            await agenticTestsRejectCreate(projectId(), id)
            actions.loadTests()
        },
    })),
    selectors({
        passingCount: [(s) => [s.tests], (tests) => tests.filter((t) => t.last_run?.status === 'passed').length],
        failingCount: [(s) => [s.tests], (tests) => tests.filter((t) => t.last_run?.status === 'failed').length],
        proposedCount: [(s) => [s.tests], (tests) => tests.filter((t) => t.status === 'proposed').length],
        proposedTests: [(s) => [s.tests], (tests) => tests.filter((t) => t.status === 'proposed')],
        filteredTests: [
            (s) => [s.tests, s.searchTerm, s.statusFilter],
            (tests: AgenticTest[], searchTerm: string, statusFilter: StatusFilter): AgenticTest[] => {
                const search = searchTerm.trim().toLowerCase()
                const matches = tests.filter((t: AgenticTest) => {
                    if (t.status === 'proposed') {
                        return false
                    }
                    if (statusFilter !== 'all' && t.status !== (statusFilter as AgenticTestStatus)) {
                        return false
                    }
                    if (search && !t.name.toLowerCase().includes(search)) {
                        return false
                    }
                    return true
                })
                return matches.sort(
                    (a, b) => STATUS_ORDER[a.status as AgenticTestStatus] - STATUS_ORDER[b.status as AgenticTestStatus]
                )
            },
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadTests()
        },
    })),
])
