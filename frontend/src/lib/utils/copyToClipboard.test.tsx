import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from './copyToClipboard'

describe('copyToClipboard', () => {
    let infoSpy: jest.SpyInstance
    let dismissSpy: jest.SpyInstance
    let nextToastId: number

    beforeEach(() => {
        nextToastId = 0
        infoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => nextToastId++)
        dismissSpy = jest.spyOn(lemonToast, 'dismiss').mockImplementation(() => {})
        Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } })
    })

    afterEach(() => {
        infoSpy.mockRestore()
        dismissSpy.mockRestore()
    })

    it('dismisses the previous copy toast before showing the next one', async () => {
        await copyToClipboard('project-id-value', 'project ID')
        expect(dismissSpy).not.toHaveBeenCalled()
        expect(infoSpy).toHaveBeenCalledWith('Copied project ID to clipboard', expect.anything())

        await copyToClipboard('us', 'project region')
        expect(dismissSpy).toHaveBeenCalledWith(0)
        expect(infoSpy).toHaveBeenCalledWith('Copied project region to clipboard', expect.anything())
    })
})
