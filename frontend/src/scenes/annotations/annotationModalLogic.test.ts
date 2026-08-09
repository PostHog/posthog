import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { annotationModalLogic } from './annotationModalLogic'

describe('annotationModalLogic', () => {
    let logic: ReturnType<typeof annotationModalLogic.build>

    useMocks({
        get: {
            '/api/environments/:team_id/annotations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => {
        initKeaTests()
        logic = annotationModalLogic()
        logic.mount()
    })

    it('keeps the modal open when a non-owner overlay unmounts', async () => {
        logic.actions.openModalToCreateAnnotation(null, null, null, 'overlay-a')
        await expectLogic(logic).toMatchValues({ isModalOpen: true, modalOwnerKey: 'overlay-a' })

        // A different overlay unmounting must not close a modal it did not open.
        logic.actions.closeModalForOwner('overlay-b')
        await expectLogic(logic).toMatchValues({ isModalOpen: true })
    })

    it('closes the modal when the owning overlay unmounts', async () => {
        logic.actions.openModalToCreateAnnotation(null, null, null, 'overlay-a')
        await expectLogic(logic).toMatchValues({ isModalOpen: true })

        logic.actions.closeModalForOwner('overlay-a')
        await expectLogic(logic).toMatchValues({ isModalOpen: false, modalOwnerKey: null })
    })
})
