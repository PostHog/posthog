import * as schedule from 'node-schedule'

export function cancelAllScheduledJobs(): void {
    Object.values(schedule.scheduledJobs).forEach((job) => {
        job.cancel()
    })
}
