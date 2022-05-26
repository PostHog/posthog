import { JobQueueExport, JobQueuePersistence, JobQueueType } from '../../types'
import { GraphileQueue } from './concurrent/graphile-queue'
import { FsQueue } from './local/fs-queue'

export const jobQueues: JobQueueExport[] = [
    {
        type: JobQueueType.Graphile,
        persistence: JobQueuePersistence.Concurrent,
        getQueue: (serverConfig) => new GraphileQueue(serverConfig),
    },
    {
        type: JobQueueType.FS,
        persistence: JobQueuePersistence.Local,
        getQueue: () => new FsQueue(),
    },
]

export const jobQueueMap = Object.fromEntries(jobQueues.map((q) => [q.type, q]))
