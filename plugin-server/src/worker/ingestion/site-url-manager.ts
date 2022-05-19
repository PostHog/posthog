import { Hub } from '../../types'

export class SiteUrlManager {
    hub: Hub
    fetchPromise?: Promise<string | null>

    constructor(hub: Hub) {
        this.hub = hub
    }

    async getSiteUrl(): Promise<string | null> {
        if (this.hub.SITE_URL) {
            return this.hub.SITE_URL
        }
        if (this.fetchPromise) {
            return this.fetchPromise
        }
        this.fetchPromise = this.hub.db.fetchConstanceSetting<string>('INGESTION_SITE_URL')
        return await this.fetchPromise!
    }

    async updateIngestionSiteUrl(newSiteUrl: string): Promise<void> {
        if (this.hub.SITE_URL || !newSiteUrl) {
            return
        }

        const existingSiteUrl = await this.getSiteUrl()
        if (existingSiteUrl !== newSiteUrl) {
            this.fetchPromise = Promise.resolve(newSiteUrl)
            await this.hub.db.upsertConstanceSetting('INGESTION_SITE_URL', newSiteUrl)
        }
    }
}
