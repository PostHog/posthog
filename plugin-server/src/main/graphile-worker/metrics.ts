import { Counter } from 'prom-client'

export const graphileEnqueueJobCounter = new Counter({
    name: 'graphile_enqueue_job',
    help: 'Result status of enqueueing a job to the graphile worker queue',
    labelNames: ['status', 'job'],
})

export const graphileScheduledTaskCounter = new Counter({
    name: 'graphile_scheduled_task',
    help: 'Graphile scheduled task status change',
    labelNames: ['status', 'task'],
})
