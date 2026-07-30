import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'

describe('notebookKernelInfoLogic', () => {
    let kernelStatusSpy: jest.SpyInstance
    let logic: ReturnType<typeof notebookKernelInfoLogic.build>

    beforeEach(() => {
        initKeaTests()
        kernelStatusSpy = jest.spyOn(api.notebooks, 'kernelStatus').mockResolvedValue({ backend: 'docker' })
    })

    afterEach(() => {
        logic?.unmount()
        kernelStatusSpy.mockRestore()
    })

    it('polls kernel status for a persisted notebook', async () => {
        logic = notebookKernelInfoLogic({ shortId: 'abc123' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(kernelStatusSpy).toHaveBeenCalledWith('abc123')
    })

    // Templates and canvases have no notebook row, so any kernel request 404s — the poll used to
    // fire anyway, once on mount and then every 10s for as long as the notebook stayed open.
    it.each([
        ['template', 'template-introduction'],
        ['canvas', 'canvas-abc123'],
    ])('does not request kernel status for a %s', async (_, shortId) => {
        logic = notebookKernelInfoLogic({ shortId })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(kernelStatusSpy).not.toHaveBeenCalled()
        expect(logic.values.kernelInfo).toBeNull()
    })
})
