import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CountedPaginatedResponse } from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { objectsEqual, toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { Experiment } from '~/types'

import type { addExperimentsToNotebookModalLogicType } from './addExperimentsToNotebookModalLogicType'

export interface ExperimentsModalFilters {
    search?: string
    page?: number
    order?: string
}

const EXPERIMENTS_PER_PAGE = 10

export const addExperimentsToNotebookModalLogic = kea<addExperimentsToNotebookModalLogicType>([
    path(['scenes', 'notebooks', 'AddExperimentsToNotebookModal', 'addExperimentsToNotebookModalLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        openModal: (insertionPosition: number | null) => ({ insertionPosition }),
        closeModal: true,
        setModalFilters: (filters: Partial<ExperimentsModalFilters>, merge: boolean = true) => ({ filters, merge }),
        setModalPage: (page: number) => ({ page }),
        loadExperiments: true,
    }),
    loaders(({ values }) => ({
        experiments: {
            __default: { results: [] as Experiment[], count: 0 } as CountedPaginatedResponse<Experiment>,
            loadExperiments: async (_, breakpoint) => {
                await breakpoint(300)

                const { order, page = 1, search } = values.filters
                const perPage = EXPERIMENTS_PER_PAGE

                const params: Record<string, any> = {
                    limit: perPage,
                    offset: Math.max(0, (page - 1) * perPage),
                }

                if (search) {
                    params.search = search
                }
                if (order) {
                    params.order = order
                }

                const response = await api.get(`api/projects/${values.currentTeamId}/experiments/?${toParams(params)}`)

                breakpoint()
                return response
            },
        },
    })),
    reducers({
        isAddExperimentsToNotebookModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        insertionPosition: [
            null as number | null,
            {
                openModal: (_, { insertionPosition }) => insertionPosition,
                closeModal: () => null,
            },
        ],
        rawModalFilters: [
            { page: 1, order: '-created_at' } as ExperimentsModalFilters,
            {
                setModalFilters: (state, { filters, merge }) => ({
                    ...(merge ? state : {}),
                    ...filters,
                    ...('page' in filters ? {} : { page: 1 }),
                }),
                closeModal: () => ({ page: 1, order: '-created_at' }),
            },
        ],
    }),
    selectors({
        filters: [
            (s) => [s.rawModalFilters],
            (rawModalFilters): ExperimentsModalFilters => ({
                page: 1,
                order: '-created_at',
                ...rawModalFilters,
            }),
        ],
        experimentsPerPage: [() => [], (): number => EXPERIMENTS_PER_PAGE],
        count: [(s) => [s.experiments], (experiments) => experiments.count],
        modalPage: [(s) => [s.filters], (filters) => filters.page || 1],
        sorting: [
            (s) => [s.filters],
            (filters): Sorting | null =>
                filters.order
                    ? filters.order.startsWith('-')
                        ? { columnKey: filters.order.slice(1), order: -1 }
                        : { columnKey: filters.order, order: 1 }
                    : null,
        ],
    }),
    listeners(({ actions, values, selectors }) => ({
        openModal: () => {
            actions.loadExperiments()
        },
        setModalPage: ({ page }) => {
            actions.setModalFilters({ page }, true)
        },
        setModalFilters: (_, __, ___, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const newFilters = values.filters

            if (!objectsEqual(oldFilters, newFilters)) {
                actions.loadExperiments()
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.isAddExperimentsToNotebookModalOpen) {
                actions.loadExperiments()
            }
        },
    })),
])
