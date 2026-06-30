import { urls } from './urls'

describe('urls', () => {
    it('links to the web analytics recap scene', () => {
        expect(urls.webAnalyticsRecap()).toEqual('/web/recap')
    })

    it.each(['Postgres', 'MySQL', 'Snowflake'] as const)(
        'includes direct access method when opening the new %s source wizard in direct mode',
        (sourceType) => {
            expect(urls.dataWarehouseSourceNew(sourceType, undefined, undefined, 'direct')).toEqual(
                `/data-warehouse/new-source?kind=${sourceType}&access_method=direct`
            )
        }
    )
})
