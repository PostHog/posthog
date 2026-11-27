import { pageCount, pageParams } from './offsetPaging'

describe('offsetPaging', () => {
    it.each([
        ['the first page starts at zero', 0, 50, { limit: 50, offset: 0 }],
        ['a later page skips the pages before it', 2, 50, { limit: 50, offset: 100 }],
    ])('%s', (_name, pageIndex, limit, expected) => {
        expect(pageParams(pageIndex, limit)).toEqual(expected)
    })

    it.each([
        ['no rows has no pages', 0, 50, 0],
        ['a partial page counts as a page', 1, 50, 1],
        ['full pages need no extra page', 100, 50, 2],
        ['a row past full pages adds a page', 101, 50, 3],
    ])('%s', (_name, count, limit, expected) => {
        expect(pageCount(count, limit)).toEqual(expected)
    })
})
