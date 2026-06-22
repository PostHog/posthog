import { urls } from './urls'

describe('urls', () => {
    it.each(['Postgres', 'MySQL'] as const)(
        'includes direct access method when opening the new %s source wizard in direct mode',
        (sourceType) => {
            expect(urls.dataWarehouseSourceNew(sourceType, undefined, undefined, 'direct')).toEqual(
                `/data-warehouse/new-source?kind=${sourceType}&access_method=direct`
            )
        }
    )
})
