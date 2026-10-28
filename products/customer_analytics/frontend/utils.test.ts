import { loadEveryPage } from './utils'

describe('loadEveryPage', () => {
    it('keeps requesting pages until it has every result', async () => {
        const items = Array.from({ length: 148 }, (_, index) => index)
        const loadPage = jest.fn(async ({ limit, offset }: { limit: number; offset: number }) => ({
            count: items.length,
            results: items.slice(offset, offset + limit),
        }))

        await expect(loadEveryPage(loadPage)).resolves.toEqual(items)
        expect(loadPage.mock.calls.map(([params]) => params)).toEqual([
            { limit: 100, offset: 0 },
            { limit: 100, offset: 100 },
        ])
    })
})
