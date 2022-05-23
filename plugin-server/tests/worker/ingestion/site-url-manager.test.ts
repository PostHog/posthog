import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { SiteUrlManager } from '../../../src/worker/ingestion/site-url-manager'
import { createPromise } from '../../helpers/promises'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

describe('SiteUrlManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    function siteUrlManager(SITE_URL: string | null = null) {
        return new SiteUrlManager(hub.db, SITE_URL)
    }

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub()
    })

    afterEach(async () => {
        await closeHub()
    })

    describe('getSiteUrl()', () => {
        it('returns env.SITE_URL if set', async () => {
            await hub.db.upsertInstanceSetting('INGESTION_SITE_URL', 'http://posthog.com')

            const result = await siteUrlManager('http://example.com').getSiteUrl()
            expect(result).toEqual('http://example.com')
        })

        it('returns INGESTION_SITE_URL if set', async () => {
            await hub.db.upsertInstanceSetting('INGESTION_SITE_URL', 'http://posthog.com')

            const result = await siteUrlManager().getSiteUrl()
            expect(result).toEqual('http://posthog.com')
        })

        it('returns null if SITE_URL or INGESTION_SITE_URL not set', async () => {
            const result = await siteUrlManager().getSiteUrl()
            expect(result).toEqual(null)
        })

        it('handles parallel fetches without querying the db many times', async () => {
            const mockPromise = createPromise<string>()
            const fetchInstanceSettingSpy = jest
                .spyOn(hub.db, 'fetchInstanceSetting')
                .mockImplementation(() => mockPromise.promise)

            const manager = siteUrlManager()
            const promises = [manager.getSiteUrl(), manager.getSiteUrl(), manager.getSiteUrl()]

            mockPromise.resolve('http://example.com')
            const results = await Promise.all(promises)

            expect(results).toEqual(['http://example.com', 'http://example.com', 'http://example.com'])
            expect(fetchInstanceSettingSpy).toHaveBeenCalledTimes(1)
        })
    })

    describe('updateIngestionSiteUrl()', () => {
        beforeEach(() => {
            jest.spyOn(hub.db, 'upsertInstanceSetting')
        })

        it('updates site_url if it changes', async () => {
            const manager = siteUrlManager()

            await manager.updateIngestionSiteUrl('http://posthog.com')

            expect(await manager.getSiteUrl()).toEqual('http://posthog.com')
            expect(hub.db.upsertInstanceSetting).toHaveBeenCalledWith('INGESTION_SITE_URL', 'http://posthog.com')
        })

        it('does nothing if SITE_URL is set', async () => {
            const manager = siteUrlManager('http://example.com')

            await manager.updateIngestionSiteUrl('http://posthog.com')

            expect(await manager.getSiteUrl()).toEqual('http://example.com')
            expect(hub.db.upsertInstanceSetting).not.toHaveBeenCalled()
        })

        it('does nothing if new site url is not set', async () => {
            const manager = siteUrlManager()

            await manager.updateIngestionSiteUrl('')

            expect(await manager.getSiteUrl()).toEqual(null)
            expect(hub.db.upsertInstanceSetting).not.toHaveBeenCalled()
        })

        it('does nothing if site url does not change', async () => {
            await hub.db.upsertInstanceSetting('INGESTION_SITE_URL', 'http://posthog.com')
            jest.mocked(hub.db.upsertInstanceSetting).mockClear()

            const manager = siteUrlManager()

            expect(await manager.getSiteUrl()).toEqual('http://posthog.com')
            await manager.updateIngestionSiteUrl('http://posthog.com')

            expect(await manager.getSiteUrl()).toEqual('http://posthog.com')
            expect(hub.db.upsertInstanceSetting).not.toHaveBeenCalled()
        })
    })
})
