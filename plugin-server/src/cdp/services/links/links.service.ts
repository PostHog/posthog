import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'
import { PromiseScheduler } from '~/utils/promise-scheduler'

import { Hub } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'

export type LinkType = {
    id: string
    team_id: number
    short_link: string
    redirect_url: string
}

// TODO: Add redis based bloom filter as first step to decide whether to lookup fully or not...
export class LinksService {
    private lazyLoader: LazyLoader<LinkType>
    private promises: PromiseScheduler
    private hogFunctionMonitoringService: HogFunctionMonitoringService

    constructor(private hub: Hub) {
        this.promises = new PromiseScheduler()
        this.lazyLoader = new LazyLoader({
            name: 'link_manager',
            loader: async (ids) => await this.fetchLinks(ids),
        })
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(hub)
    }

    async stop() {
        await this.promises.waitForAllSettled()
    }

    async processLink(req: ModifiedRequest, res: express.Response): Promise<void> {
        const id = req.params.id
        const domain = this.hub.SHORT_LINKS_DOMAIN
        const shortLink = `${domain}/${id}`
        const link = await this.lazyLoader.get(shortLink)

        if (!link) {
            res.status(404).send('Not found')
            return
        }

        this.hogFunctionMonitoringService.queueAppMetric(
            {
                app_source_id: link.id,
                metric_kind: 'success',
                metric_name: 'succeeded',
                team_id: link.team_id,
                count: 1,
            },
            'link'
        )
        void this.promises.schedule(this.hogFunctionMonitoringService.flush())

        res.redirect(link.redirect_url)
    }

    private async fetchLinks(ids: string[]): Promise<Record<string, LinkType | undefined>> {
        logger.debug('[LinkManager]', 'Fetching links', { ids })

        const response = await this.hub.postgres.query<LinkType>(
            PostgresUse.COMMON_READ,
            `select id, team_id, redirect_url from posthog_link WHERE concat(short_link_domain, '/', short_code) = ANY($1)`,
            [ids],
            'fetchShortLinks'
        )
        return response.rows.reduce<Record<string, LinkType | undefined>>((acc, link) => {
            acc[link.short_link] = link
            return acc
        }, {})
    }
}
