import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { panelLayoutLogic } from './panelLayoutLogic'

function rect(width: number, height: number): DOMRect {
    return { x: 0, y: 0, top: 0, left: 0, right: width, bottom: height, width, height, toJSON: () => ({}) } as DOMRect
}

describe('panelLayoutLogic', () => {
    let logic: ReturnType<typeof panelLayoutLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = panelLayoutLogic()
        logic.mount()
    })

    describe('setMainContentRect', () => {
        it('stores a non-zero rect', async () => {
            await expectLogic(logic, () => {
                logic.actions.setMainContentRect(rect(800, 600))
            }).toMatchValues({ mainContentRect: expect.objectContaining({ width: 800, height: 600 }) })
        })

        it('ignores a zero-width rect so the scene container is not blanked mid-transition', async () => {
            logic.actions.setMainContentRect(rect(800, 600))
            await expectLogic(logic).toMatchValues({
                mainContentRect: expect.objectContaining({ width: 800, height: 600 }),
            })

            logic.actions.setMainContentRect(rect(0, 600))
            await expectLogic(logic).toMatchValues({
                mainContentRect: expect.objectContaining({ width: 800, height: 600 }),
            })
        })

        it('ignores a zero-height rect for the same reason', async () => {
            logic.actions.setMainContentRect(rect(800, 600))
            logic.actions.setMainContentRect(rect(800, 0))
            await expectLogic(logic).toMatchValues({
                mainContentRect: expect.objectContaining({ width: 800, height: 600 }),
            })
        })

        it('accepts the next valid rect after a zero measurement is ignored', async () => {
            logic.actions.setMainContentRect(rect(800, 600))
            logic.actions.setMainContentRect(rect(0, 0))
            logic.actions.setMainContentRect(rect(1024, 768))
            await expectLogic(logic).toMatchValues({
                mainContentRect: expect.objectContaining({ width: 1024, height: 768 }),
            })
        })
    })
})
