import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { deleteWithUndo } from './deleteWithUndo'

describe('deleteWithUndo', () => {
    let updateSpy: jest.SpyInstance

    beforeEach(() => {
        updateSpy = jest.spyOn(api, 'update').mockResolvedValue({})
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('offers no undo when the item is not undoable', async () => {
        const infoSpy = jest.spyOn(lemonToast, 'info')

        await deleteWithUndo({ endpoint: 'projects/1/feature_flags', object: { id: 7 }, undoable: false })

        expect(infoSpy.mock.calls[0][1]?.button).toBeUndefined()
    })

    it.each([
        [true, 0],
        [false, 1],
    ])('shows the error toast only when onError does not handle the error (handled: %s)', async (handled, toasts) => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        updateSpy.mockRejectedValue({ status: 409, detail: 'Changed elsewhere' })
        const onError = jest.fn(() => handled)

        await deleteWithUndo({ endpoint: 'projects/1/feature_flags', object: { id: 7 }, onError })

        expect(onError).toHaveBeenCalledWith({ status: 409, detail: 'Changed elsewhere' })
        expect(errorSpy).toHaveBeenCalledTimes(toasts)
    })
})
