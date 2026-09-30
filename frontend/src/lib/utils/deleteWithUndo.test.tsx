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
            payload: {},
        })
        expect(updateSpy).toHaveBeenLastCalledWith('api/projects/1/feature_flags/7', { deleted: true })

        const undoButton = infoSpy.mock.calls[0][1]?.button
        expect(undoButton?.label).toBe('Undo')
        await undoButton?.action()
        expect(updateSpy).toHaveBeenLastCalledWith('api/projects/1/feature_flags/7', { deleted: false })
    })
})
