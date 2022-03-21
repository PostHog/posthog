import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, TeamId } from '../types'
import { UUIDT } from './utils'

export class InternalMetrics {
    metrics: Record<string, number>
    teamId: TeamId | null | undefined

    hub: Hub

    constructor(hub: Hub) {
        this.metrics = {}
        this.teamId = undefined

        this.hub = hub
    }

    incr(metric: string): void {
        this.metrics[metric] = (this.metrics[metric] || 0) + 1
    }

    async flush(piscina: Piscina): Promise<void> {
        const teamId = await this.getTeamId()
        if (!teamId) {
            return
        }

        const metrics = this.metrics
        this.metrics = {}
        const promises: Array<Promise<any>> = []

        for (const key of Object.keys(metrics)) {
            const event: PluginEvent = {
                event: key,
                properties: { value: metrics[key] },
                distinct_id: 'plugin_server',
                team_id: teamId,
                ip: null,
                site_url: '',
                now: new Date().toISOString(),
                uuid: new UUIDT().toString(),
            }

            promises.push(piscina.run({ task: 'ingestEvent', args: { event } }))
        }

        await Promise.all(promises)
    }

    async getTeamId(): Promise<TeamId | null> {
        if (this.hub.CAPTURE_INTERNAL_METRICS && this.teamId === undefined) {
            this.teamId = await this.hub.db.fetchInternalMetricsTeam()
        }
        return this.teamId || null
    }
}
