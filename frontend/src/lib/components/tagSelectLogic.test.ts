import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { tagSelectLogic } from './tagSelectLogic'

describe('tagSelectLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/tags': [200, ['tag-a', 'tag-b']],
            },
        })
        initKeaTests()
    })

    it('keeps popover state isolated between instances with different keys', async () => {
        const tagsLogic = tagSelectLogic({ logicKey: 'tags' })
        const excludedTagsLogic = tagSelectLogic({ logicKey: 'excluded-tags' })
        tagsLogic.mount()
        excludedTagsLogic.mount()

        // Opening one dropdown must not open the other — guards against the logic
        // regressing to a singleton that shares showPopover across instances.
        await expectLogic(tagsLogic, () => {
            tagsLogic.actions.setShowPopover(true)
        }).toMatchValues({ showPopover: true })

        await expectLogic(excludedTagsLogic).toMatchValues({ showPopover: false })
    })
})
