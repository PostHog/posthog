import { afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { projectLogic } from 'scenes/projectLogic'

import { experimentsFlagCleanupTaskRetrieve } from 'products/experiments/frontend/generated/api'
import type { ExperimentFlagCleanupTaskApi } from 'products/experiments/frontend/generated/api.schemas'

import type { flagCleanupTaskLogicType } from './flagCleanupTaskLogicType'

export interface FlagCleanupTaskLogicProps {
    experimentId: number
}

const POLL_INTERVAL_MS = 30000

export const flagCleanupTaskLogic = kea<flagCleanupTaskLogicType>([
    props({} as FlagCleanupTaskLogicProps),
    key((props) => props.experimentId),
    path((key) => ['scenes', 'experiments', 'flagCleanupTaskLogic', key]),
    connect(() => ({ values: [projectLogic, ['currentProjectId']] })),
    loaders(({ props, values }) => ({
        cleanupTask: [
            null as ExperimentFlagCleanupTaskApi | null,
            {
                loadCleanupTask: async () =>
                    await experimentsFlagCleanupTaskRetrieve(String(values.currentProjectId), props.experimentId),
            },
        ],
    })),
    listeners(({ cache }) => ({
        loadCleanupTaskSuccess: ({ cleanupTask }) => {
            if (cleanupTask?.is_terminal) {
                cache.disposables.dispose('cleanupTaskPoll')
            }
        },
        loadCleanupTaskFailure: () => {
            cache.disposables.dispose('cleanupTaskPoll')
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadCleanupTask()
        cache.disposables.add(() => {
            const id = setInterval(() => actions.loadCleanupTask(), POLL_INTERVAL_MS)
            return () => clearInterval(id)
        }, 'cleanupTaskPoll')
    }),
])
