import { JobQueueExport, JobQueuePersistence, JobQueueType } from '../../types'
import { GraphileQueue } from './concurrent/graphile-queue'
import { FsQueue } from './local/fs-queue'

export const jobQueues: JobQueueExport[] = [
    {
        type: JobQueueType.Graphile,
        persistence: JobQueuePersistence.Concurrent,
        getQueue: (serverConfig) => {
            // Use JOB_QUEUE_GRAPHILE_URL if set, meaning a separate Postgres instance is used for Graphile instead of our main DB
            // Else use the main Postgres instance
            const graphileUrl = serverConfig.JOB_QUEUE_GRAPHILE_URL
            const config = graphileUrl ? { ...serverConfig, DATABASE_URL: graphileUrl } : serverConfig
            return new GraphileQueue(config)
        },
    },
    {
        /*
        On Cloud we have a separate instance dedicated solely to jobs using the Graphile queue.
        Thus we use the main Postgres DB as a Graphile-based backup queue for jobs that for some reason didn't reach 
        the dedicated instance (e.g. because it was down). We poll a lot less often to manage load and because under normal
        operations jobs should not reach this queue.

        The same works for self-hosted users that have a separate Postgres instance for jobs.
        */
        type: JobQueueType.GraphileBackup,
        persistence: JobQueuePersistence.Concurrent,
        getQueue: (serverConfig) => new GraphileQueue(serverConfig, { pollInterval: 20_000 }),
    },
    {
        type: JobQueueType.FS,
        persistence: JobQueuePersistence.Local,
        getQueue: () => new FsQueue(),
    },
]

export const jobQueueMap = Object.fromEntries(jobQueues.map((q) => [q.type, q]))
