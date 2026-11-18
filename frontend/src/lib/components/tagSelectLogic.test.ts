import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { LoadTags, excludingTags, tagSelectLogic } from './tagSelectLogic'

const loadTags: LoadTags = async () => ({ results: [], hasMore: false })

describe('tagSelectLogic', () => {
    it('replaces searched results and appends later pages', async () => {
        initKeaTests()
        const logic = tagSelectLogic({ logicKey: 'pages' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadTagPageSuccess(
                { results: [{ tag: 'alpha' }, { tag: 'beta' }], hasMore: true },
                { search: '', offset: 0, loadTags, requestEpoch: 0 }
            )
        }).toMatchValues({ hasMoreTags: true, tagResults: [{ tag: 'alpha' }, { tag: 'beta' }] })

        await expectLogic(logic, () => {
            logic.actions.loadTagPageSuccess(
                { results: [{ tag: 'gamma' }], hasMore: false },
                { search: '', offset: 2, loadTags, requestEpoch: 0 }
            )
        }).toMatchValues({ hasMoreTags: false, tagResults: [{ tag: 'alpha' }, { tag: 'beta' }, { tag: 'gamma' }] })

        await expectLogic(logic, () => {
            logic.actions.setSearch('bet')
            logic.actions.loadTagPageSuccess(
                { results: [{ tag: 'beta' }], hasMore: false },
                { search: 'bet', offset: 0, loadTags, requestEpoch: 1 }
            )
        }).toMatchValues({ search: 'bet', tagResults: [{ tag: 'beta' }] })
        expect(logic.values.tagResults).toEqual([{ tag: 'beta' }])
    })

    it('loads the next page once, from where the server left off', async () => {
        initKeaTests()
        const logic = tagSelectLogic({ logicKey: 'more' })
        logic.mount()
        let releasePage: (page: { results: never[]; hasMore: boolean }) => void = () => {}
        const loadNextPage = jest.fn<ReturnType<LoadTags>, Parameters<LoadTags>>(
            () => new Promise((resolve) => (releasePage = resolve))
        )
        logic.actions.loadTagPageSuccess(
            { results: [{ tag: 'alpha' }, { tag: 'beta' }], hasMore: true, nextOffset: 3 },
            { search: '', offset: 0, loadTags, requestEpoch: 0 }
        )

        logic.actions.loadMoreTags(loadNextPage)
        logic.actions.loadMoreTags(loadNextPage)

        expect(loadNextPage).toHaveBeenCalledTimes(1)
        expect(loadNextPage).toHaveBeenCalledWith('', 3, expect.any(Function))
        releasePage({ results: [], hasMore: false })
        await expectLogic(logic).toFinishAllListeners()
    })

    it('keeps loaded tags after a failed page so users can retry', async () => {
        initKeaTests()
        const logic = tagSelectLogic({ logicKey: 'failure' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadTagPageSuccess(
                { results: [{ tag: 'alpha' }], hasMore: true },
                { search: '', offset: 0, loadTags, requestEpoch: 0 }
            )
            logic.actions.loadTagPageFailure('Unable to load tags')
        }).toMatchValues({ tagPageError: 'Unable to load tags', tagResults: [{ tag: 'alpha' }] })
        expect(logic.values.tagPageError).toBe('Unable to load tags')
    })

    it('skips past pages whose tags are all excluded', async () => {
        const pages: Record<number, Awaited<ReturnType<LoadTags>>> = {
            0: { results: [{ tag: 'a,b' }, { tag: 'c,d' }], hasMore: true },
            2: { results: [{ tag: 'e,f' }, { tag: 'valid' }], hasMore: true },
        }
        const loadPage = jest.fn<ReturnType<LoadTags>, Parameters<LoadTags>>(async (_, offset) => pages[offset])

        const page = await excludingTags(loadPage, (tag) => tag.includes(','))('', 0)

        expect(page).toEqual({ results: [{ tag: 'valid' }], hasMore: true, nextOffset: 4 })
        expect(loadPage.mock.calls).toEqual([
            ['', 0],
            ['', 2],
        ])
    })

    it('stops loading excluded pages once the search is stale', async () => {
        const loadPage = jest.fn<ReturnType<LoadTags>, Parameters<LoadTags>>(async (_, offset) => ({
            results: [{ tag: `excluded,${offset}` }],
            hasMore: offset < 2,
        }))

        const page = await excludingTags(loadPage, (tag) => tag.includes(','))('', 0, () => true)

        expect(page).toEqual({ results: [], hasMore: false })
        expect(loadPage).toHaveBeenCalledTimes(1)
    })
})
