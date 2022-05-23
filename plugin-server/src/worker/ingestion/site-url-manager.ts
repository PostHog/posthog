import { DB } from '../../utils/db/db'

export class SiteUrlManager {
    private db: DB
    private envSiteUrl: string | null
    private fetchPromise?: Promise<string | null>

    constructor(db: DB, envSiteUrl: string | null) {
        this.db = db
        this.envSiteUrl = envSiteUrl
    }

    async getSiteUrl(): Promise<string | null> {
        if (this.envSiteUrl) {
            return this.envSiteUrl
        }
        if (this.fetchPromise) {
            return this.fetchPromise
        }
        this.fetchPromise = this.db.fetchInstanceSetting<string>('INGESTION_SITE_URL')
        return await this.fetchPromise!
    }

    async updateIngestionSiteUrl(newSiteUrl: string | null): Promise<void> {
        if (this.envSiteUrl || !newSiteUrl) {
            return
        }

        const existingSiteUrl = await this.getSiteUrl()
        if (existingSiteUrl !== newSiteUrl) {
            this.fetchPromise = Promise.resolve(newSiteUrl)
            await this.db.upsertInstanceSetting('INGESTION_SITE_URL', newSiteUrl)
        }
    }
}
