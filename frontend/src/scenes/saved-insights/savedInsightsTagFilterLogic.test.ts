import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { savedInsightsTagFilterLogic } from './savedInsightsTagFilterLogic'

describe('savedInsightsTagFilterLogic', () => {
    it('replaces the first tag page and appends the next one', async () => {
        initKeaTests()
        const logic = savedInsightsTagFilterLogic({ logicKey: 'test' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadTagResultsSuccess(
                { next: 'next-page', previous: null, results: ['alpha', 'beta'] },
                { search: '', offset: 0 }
            )
        }).toMatchValues({ hasMoreTagResults: true, tagResults: ['alpha', 'beta'] })

        await expectLogic(logic, () => {
            logic.actions.loadTagResultsSuccess(
                { next: null, previous: 'previous-page', results: ['gamma'] },
                { search: '', offset: 2 }
            )
        }).toMatchValues({ hasMoreTagResults: false, tagResults: ['alpha', 'beta', 'gamma'] })
    })

    it('keeps loaded tags and exposes a failed page for retry', async () => {
        initKeaTests()
        const logic = savedInsightsTagFilterLogic({ logicKey: 'failure' })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadTagResultsSuccess(
                { next: 'next-page', previous: null, results: ['alpha'] },
                { search: '', offset: 0 }
            )
            logic.actions.loadTagResultsFailure('Unable to load tags')
        }).toMatchValues({ tagPageError: 'Unable to load tags', tagResults: ['alpha'] })
    })
})
