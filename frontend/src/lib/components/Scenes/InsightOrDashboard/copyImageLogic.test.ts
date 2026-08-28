import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { copyImageLogic } from './copyImageLogic'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
}))

const SELECTOR = '[data-attr="insights-graph"]'

describe('copyImageLogic', () => {
    let logic: ReturnType<typeof copyImageLogic.build>
    let write: jest.Mock

    beforeEach(() => {
        initKeaTests()
        document.body.innerHTML = `<div data-attr="insights-graph">chart</div>`

        write = jest.fn(() => Promise.resolve())
        Object.defineProperty(navigator, 'clipboard', { value: { write }, configurable: true })
        // jsdom has no ClipboardItem, and the logic treats its absence as "this browser cannot copy images".
        ;(global as any).ClipboardItem = jest.fn((items) => items)

        jest.spyOn(lemonToast, 'success').mockImplementation(() => '' as any)
        jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        logic = copyImageLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
        delete (global as any).ClipboardItem
    })

    it('puts the element on the clipboard and clears the in-flight state', async () => {
        await expectLogic(logic, () => {
            logic.actions.copyImage(SELECTOR)
        }).toFinishAllListeners()

        expect(write).toHaveBeenCalledTimes(1)
        expect(lemonToast.success).toHaveBeenCalled()
        expect(logic.values.isCopying).toBe(false)
    })

    it('clears the in-flight state when the clipboard write fails', async () => {
        write.mockRejectedValueOnce(new Error('denied'))

        await expectLogic(logic, () => {
            logic.actions.copyImage(SELECTOR)
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.isCopying).toBe(false)
    })

    it('reports a browser without clipboard image support instead of capturing', async () => {
        delete (global as any).ClipboardItem

        await expectLogic(logic, () => {
            logic.actions.copyImage(SELECTOR)
        }).toFinishAllListeners()

        expect(write).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalled()
    })

    it('reports a missing target instead of copying an empty image', async () => {
        document.body.innerHTML = ''

        await expectLogic(logic, () => {
            logic.actions.copyImage(SELECTOR)
        }).toFinishAllListeners()

        expect(write).not.toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalled()
    })
})
