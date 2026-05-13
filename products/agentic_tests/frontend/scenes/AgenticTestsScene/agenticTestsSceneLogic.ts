import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { AgenticTest, AgenticTestStatus } from '../../types'
import type { agenticTestsSceneLogicType } from './agenticTestsSceneLogicType'

export type StatusFilter = 'all' | 'active' | 'paused' | 'rejected'

const baseUrl = (): string => `api/projects/${getCurrentTeamId()}/agentic_tests/`

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
                    const response = await api.get<{ results: AgenticTest[] }>(baseUrl())
                    return response.results
                },
            },
        ],
    }),
    listeners(({ actions }) => ({
        deleteTest: async ({ id }) => {
            await api.delete(`${baseUrl()}${id}/`)
            actions.loadTests()
        },
        runNow: async ({ id }) => {
            await api.create(`${baseUrl()}${id}/run_now/`, {})
            actions.loadTests()
        },
        activateTest: async ({ id }) => {
            await api.create(`${baseUrl()}${id}/activate/`, {})
            actions.loadTests()
        },
        pauseTest: async ({ id }) => {
            await api.create(`${baseUrl()}${id}/pause/`, {})
            actions.loadTests()
        },
        rejectTest: async ({ id }) => {
            await api.create(`${baseUrl()}${id}/reject/`, {})
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
                return tests.filter((t: AgenticTest) => {
                    if (t.status === 'proposed') {
                        return false
                    }
                    if (statusFilter === 'all') {
                        // Default 'all' hides rejected — match the workflows archived pattern.
                        if (t.status === 'rejected') {
                            return false
                        }
                    } else if (t.status !== (statusFilter as AgenticTestStatus)) {
                        return false
                    }
                    if (search && !t.name.toLowerCase().includes(search)) {
                        return false
                    }
                    return true
                })
            },
        ],
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadTests()
        },
    })),
])
