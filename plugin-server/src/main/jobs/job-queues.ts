import { JobQueueExport, JobQueuePersistence, JobQueueType } from '../../types'
import { GraphileWorker } from './graphile-worker'
import { MockGraphileWorker } from './local/fs-queue'

export const jobQueues: JobQueueExport[] = [
    {
        type: JobQueueType.Graphile,
        persistence: JobQueuePersistence.Concurrent,
        getQueue: (serverConfig) => {
            const config = serverConfig.JOB_QUEUE_GRAPHILE_URL
                ? { ...serverConfig, DATABASE_URL: serverConfig.JOB_QUEUE_GRAPHILE_URL }
                : serverConfig
            return new GraphileWorker(config)
        },
    },
    {
        type: JobQueueType.FS,
        persistence: JobQueuePersistence.Local,
        getQueue: () => new MockGraphileWorker(),
    },
]

export const jobQueueMap = Object.fromEntries(jobQueues.map((q) => [q.type, q]))
