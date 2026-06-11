import { urls } from './urls'

describe('urls', () => {
    it('includes direct access method when opening the new Postgres source wizard in direct mode', () => {
        expect(urls.dataWarehouseSourceNew('Postgres', undefined, undefined, 'direct')).toEqual(
            '/data-warehouse/new-source?kind=Postgres&access_method=direct'
        )
    })
})
