import { CronItem, JobHelpers, TaskList } from 'graphile-worker'
import { Counter } from 'prom-client'

import { EnqueuedPluginJob, Hub } from '../../types'
import { status } from '../../utils/status'
import Piscina from '../../worker/piscina'
import { GraphileWorker } from './graphile-worker'
import { loadPluginSchedule, runScheduledTasks } from './schedule'

const jobsTriggeredCounter = new Counter({
    name: 'jobs_triggered_total',
    help: 'Number of jobs consumed from the Graphile job queue.',
    labelNames: ['job_type'],
})

const jobsExecutionSuccessCounter = new Counter({
    name: 'jobs_execution_success_total',
    help: 'Number of jobs successfully executed from the Graphile job queue.',
    labelNames: ['job_type'],
})

const jobsExecutionFailureCounter = new Counter({
    name: 'jobs_execution_failure_total',
    help: 'Number of failures at executing jobs from the Graphile job queue.',
    labelNames: ['job_type'],
})

export async function startGraphileWorker(hub: Hub, graphileWorker: GraphileWorker, piscina: Piscina) {
    status.info('🔄', 'Starting Graphile Worker...')

    piscina.on('drain', () => {
        void graphileWorker.resumeConsumer()
    })

    let jobHandlers: TaskList = {}

    const crontab: CronItem[] = []

    if (hub.capabilities.processPluginJobs) {
        jobHandlers = { ...jobHandlers, ...getPluginJobHandlers(hub, graphileWorker, piscina) }
        status.info('🔄', 'Graphile Worker: set up plugin job handlers ...')
    }

    if (hub.capabilities.pluginScheduledTasks) {
        hub.pluginSchedule = await loadPluginSchedule(piscina)

        // TODO: In the future we might benefit from scheduling tasks more granularly i.e. <taskType, pluginConfigId>
        // KLUDGE: Given we're currently not doing the above, if we throw after executing n tasks for given type, those n tasks will be re-run
        // Note: backfillPeriod must be explicitly defined here (without passing options it defaults to 0 anyway) but we'd currently
        // not like to use it as it has a lot of limitations (see: https://github.com/graphile/worker#limiting-backfill)
        // We might benefit from changing this setting in the future
        crontab.push({
            task: 'runEveryMinute',
            identifier: 'runEveryMinute',
            pattern: '* * * * *',
            options: { maxAttempts: 1, backfillPeriod: 0 },
        })
        crontab.push({
            task: 'runEveryHour',
            identifier: 'runEveryHour',
            pattern: '0 * * * *',
            options: { maxAttempts: 5, backfillPeriod: 0 },
        })
        crontab.push({
            task: 'runEveryDay',
            identifier: 'runEveryDay',
            pattern: '0 0 * * *',
            options: { maxAttempts: 10, backfillPeriod: 0 },
        })

        jobHandlers = {
            ...jobHandlers,
            ...getScheduledTaskHandlers(hub, piscina),
        }

        status.info('🔄', 'Graphile Worker: set up scheduled task handlers...')
    }

    await graphileWorker.start(jobHandlers, crontab)
    return graphileWorker
}

export function getPluginJobHandlers(hub: Hub, graphileWorker: GraphileWorker, piscina: Piscina): TaskList {
    const pluginJobHandlers: TaskList = {
        pluginJob: async (job) => {
            const jobType = (job as EnqueuedPluginJob)?.type
            jobsTriggeredCounter.labels(jobType).inc()
            try {
                await piscina.run({ task: 'runPluginJob', args: { job: job as EnqueuedPluginJob } })
                jobsExecutionSuccessCounter.labels(jobType).inc()
            } catch (e) {
                jobsExecutionFailureCounter.labels(jobType).inc()
                throw e
            }
        },
    }

    return pluginJobHandlers
}

export function getScheduledTaskHandlers(hub: Hub, piscina: Piscina): TaskList {
    const scheduledTaskHandlers: TaskList = {
        runEveryMinute: async (_, helpers: JobHelpers) =>
            await runScheduledTasks(hub, piscina, 'runEveryMinute', helpers),
        runEveryHour: async (_, helpers: JobHelpers) => await runScheduledTasks(hub, piscina, 'runEveryHour', helpers),
        runEveryDay: async (_, helpers: JobHelpers) => await runScheduledTasks(hub, piscina, 'runEveryDay', helpers),
    }

    return scheduledTaskHandlers
}
