import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { LoadTags, tagSelectLogic } from './tagSelectLogic'

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
})
