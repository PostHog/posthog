import * as schedule from 'node-schedule'

import { PluginFunction } from './../types'
import { posthog } from './posthog'

class PluginDurationStats {
    total: number
    onEvent: number
    processEvent: number
    onSnapshot: number
    pluginTask: number

    constructor() {
        this.total = 0
        this.onEvent = 0
        this.processEvent = 0
        this.onSnapshot = 0
        this.pluginTask = 0
    }

    public formatStatsForReport(): Record<string, number> {
        const formattedStats: Record<string, number> = {}

        for (const [entry, ms] of Object.entries(this)) {
            formattedStats[`${entry}_time_ms`] = ms
            formattedStats[`${entry}_time_seconds`] = Math.round(ms / 10) / 100
        }

        return formattedStats
    }
}

interface PluginDurationStatsPerTeam {
    [key: number]: PluginDurationStats
}

class StatusReport {
    pluginDurationStatsPerTeam: PluginDurationStatsPerTeam
    statusReportJob: schedule.Job
    statusReportJobConfigured: boolean

    constructor() {
        this.pluginDurationStatsPerTeam = {}
        this.statusReportJob = {} as schedule.Job
        this.statusReportJobConfigured = false
    }

    private captureStatusReport(): void {
        for (const [teamId, pluginStats] of Object.entries(this.pluginDurationStatsPerTeam)) {
            posthog.capture('$plugin_running_duration', {
                team: Number(teamId),
                ...pluginStats.formatStatsForReport(),
            })
        }
        this.pluginDurationStatsPerTeam = {} as PluginDurationStatsPerTeam
    }

    public addToTimeSpentRunningPlugins(teamId: number, increment: number, functionRan: PluginFunction): void {
        if (!(teamId in this.pluginDurationStatsPerTeam)) {
            this.pluginDurationStatsPerTeam[teamId] = new PluginDurationStats()
        }
        this.pluginDurationStatsPerTeam[teamId][functionRan] += increment
        this.pluginDurationStatsPerTeam[teamId].total += increment
    }

    public startStatusReportSchedule(): void {
        if (this.statusReportJobConfigured) {
            return
        }
        this.statusReportJob = schedule.scheduleJob('0 * * * *', () => {
            this.captureStatusReport()
        })
        this.statusReportJobConfigured = true
    }

    public stopStatusReportSchedule(): void {
        this.captureStatusReport()
        posthog.flush()
        if (this.statusReportJobConfigured) {
            this.statusReportJob.cancel()
        }
    }
}

export const statusReport = new StatusReport()
