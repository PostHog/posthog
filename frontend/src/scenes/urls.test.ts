import { urls } from './urls'

describe('urls', () => {
    it('links to the web analytics recap scene', () => {
        expect(urls.webAnalyticsRecap()).toEqual('/web/recap')
    })

    it('includes direct access method when opening the new Postgres source wizard in direct mode', () => {
        expect(urls.dataWarehouseSourceNew('Postgres', undefined, undefined, 'direct')).toEqual(
            '/data-warehouse/new-source?kind=Postgres&access_method=direct'
        )
    })
})
