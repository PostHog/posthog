import { render } from '@testing-library/react'

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

    it('names the toast with the label without sending it, and the undo does the same', async () => {
        const infoSpy = jest.spyOn(lemonToast, 'info')

        await deleteWithUndo({
            endpoint: 'projects/1/feature_flags',
            object: { id: 7 },
            label: 'checkout-redesign',
        })
        expect(updateSpy).toHaveBeenLastCalledWith('api/projects/1/feature_flags/7', { id: 7, deleted: true })

        const [message, options] = infoSpy.mock.calls[0]
        expect(render(message as JSX.Element).container.textContent).toBe('checkout-redesign has been deleted')
        expect(options?.button?.label).toBe('Undo')
        await options?.button?.action()
        expect(updateSpy).toHaveBeenLastCalledWith('api/projects/1/feature_flags/7', { id: 7, deleted: false })
    })
})
