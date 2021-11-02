import { JobQueueExport, JobQueuePersistence, JobQueueType } from '../../types'
import { GraphileQueue } from './concurrent/graphile-queue'
import { FsQueue } from './local/fs-queue'
import { S3Queue } from './redlocked/s3-queue'

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
    {
        type: JobQueueType.S3,
        persistence: JobQueuePersistence.Redlocked,
        getQueue: (serverConfig) => new S3Queue(serverConfig),
    },
]

export const jobQueueMap = Object.fromEntries(jobQueues.map((q) => [q.type, q]))
