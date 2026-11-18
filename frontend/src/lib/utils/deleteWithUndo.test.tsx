import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { insightsApi } from 'scenes/insights/utils/api'

import { InsightModel } from '~/types'

import { deleteInsightWithUndo, deleteWithUndo } from './deleteWithUndo'

describe('deleteWithUndo', () => {
    let updateSpy: jest.SpyInstance

    beforeEach(() => {
        updateSpy = jest.spyOn(api, 'update').mockResolvedValue({})
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('sends the whole object with deleted by default', async () => {
        await deleteWithUndo({ endpoint: 'projects/1/dashboards', object: { id: 7, name: 'Weekly metrics' } })

        expect(updateSpy).toHaveBeenCalledWith('api/projects/1/dashboards/7', {
            id: 7,
            name: 'Weekly metrics',
            deleted: true,
        })
    })

    it('sends the payload in place of the object, and the undo does the same', async () => {
        const infoSpy = jest.spyOn(lemonToast, 'info')

        await deleteWithUndo({
            endpoint: 'projects/1/feature_flags',
            object: { id: 7, name: 'checkout-redesign' },
            payload: { version: 3 },
        })
        expect(updateSpy).toHaveBeenLastCalledWith('api/projects/1/feature_flags/7', { version: 3, deleted: true })

        const undoButton = infoSpy.mock.calls[0][1]?.button
        expect(undoButton?.label).toBe('Undo')
        await undoButton?.action()
        expect(updateSpy).toHaveBeenLastCalledWith('api/projects/1/feature_flags/7', { version: 3, deleted: false })
    })

    it('offers no undo when the item is not undoable', async () => {
        const infoSpy = jest.spyOn(lemonToast, 'info')

        await deleteWithUndo({ endpoint: 'projects/1/feature_flags', object: { id: 7 }, undoable: false })

        expect(infoSpy.mock.calls[0][1]?.button).toBeUndefined()
    })

    it.each([
        [true, 0],
        [false, 1],
    ])('toasts unless handleError handles the error, then runs onError (handled: %s)', async (handled, toasts) => {
        const errorSpy = jest.spyOn(lemonToast, 'error')
        updateSpy.mockRejectedValue({ status: 409, detail: 'Changed elsewhere' })
        const handleError = jest.fn(() => handled)
        const onError = jest.fn()

        await deleteWithUndo({ endpoint: 'projects/1/feature_flags', object: { id: 7 }, handleError, onError })

        expect(handleError).toHaveBeenCalledWith({ status: 409, detail: 'Changed elsewhere' })
        expect(errorSpy).toHaveBeenCalledTimes(toasts)
        expect(onError).toHaveBeenCalledWith(false, { id: 7 })
    })

    it('restores an insight even when one of its dashboards refuses the tile', async () => {
        const warningSpy = jest.spyOn(lemonToast, 'warning')
        jest.spyOn(insightsApi, 'addToDashboard')
            .mockResolvedValueOnce({ id: 11, dashboard_id: 1 })
            .mockRejectedValueOnce({ status: 404, detail: 'Not found.' })
        const callback = jest.fn()
        const insight = {
            id: 7,
            name: 'Weekly signups',
            dashboard_tiles: [
                { id: 11, dashboard_id: 1 },
                { id: 12, dashboard_id: 2 },
            ],
        } as InsightModel

        await deleteInsightWithUndo({ undo: true, endpoint: 'projects/1/insights', object: insight, callback })

        expect(updateSpy).toHaveBeenCalledWith('api/projects/1/insights/7', expect.objectContaining({ deleted: false }))
        expect(callback).toHaveBeenCalledWith(true, insight)
        expect(warningSpy).toHaveBeenCalledTimes(1)
    })
})
