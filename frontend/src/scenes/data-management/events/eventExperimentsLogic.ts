import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { experimentsList } from 'products/experiments/frontend/generated/api'
import type {
    ExperimentBasicApi,
    PaginatedExperimentBasicListApi,
} from 'products/experiments/frontend/generated/api.schemas'

import type { eventExperimentsLogicType } from './eventExperimentsLogicType'

export interface EventExperimentsLogicProps {
    event: string
}

export const EXPERIMENTS_PER_PAGE = 10

const EMPTY_RESULT: PaginatedExperimentBasicListApi = { count: 0, next: null, previous: null, results: [] }

export const eventExperimentsLogic = kea<eventExperimentsLogicType>([
    path(['scenes', 'data-management', 'events', 'eventExperimentsLogic']),
    props({} as EventExperimentsLogicProps),
    key(({ event }) => event),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        setPage: (page: number) => ({ page }),
    }),
    reducers({
        page: [1, { setPage: (_, { page }) => page }],
    }),
    loaders(({ values, props }) => ({
        experiments: [
            EMPTY_RESULT,
            {
                loadExperiments: async (): Promise<PaginatedExperimentBasicListApi> => {
                    return await experimentsList(String(values.currentProjectId), {
                        event: props.event,
                        limit: EXPERIMENTS_PER_PAGE,
                        offset: Math.max(0, (values.page - 1) * EXPERIMENTS_PER_PAGE),
                    })
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setPage: () => {
            actions.loadExperiments()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadExperiments()
    }),
])

export type { ExperimentBasicApi }
