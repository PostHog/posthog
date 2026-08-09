import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from './copyToClipboard'

describe('copyToClipboard', () => {
    const writeText = jest.fn()
    const execCommand = jest.fn()
    let infoSpy: jest.SpyInstance
    let errorSpy: jest.SpyInstance
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        writeText.mockReset()
        execCommand.mockReset()
        Object.assign(navigator, { clipboard: { writeText } })
        document.execCommand = execCommand
        infoSpy = jest.spyOn(lemonToast, 'info').mockImplementation(() => '' as any)
        errorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)
        captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('reports success when the Clipboard API writes the value', async () => {
        writeText.mockResolvedValue(undefined)

        await expect(copyToClipboard('data', 'table')).resolves.toBe(true)

        expect(infoSpy).toHaveBeenCalledWith('Copied table to clipboard', expect.anything())
        expect(errorSpy).not.toHaveBeenCalled()
        expect(captureSpy).not.toHaveBeenCalled()
    })

    it('reports success when the Clipboard API rejects but the textarea fallback copies', async () => {
        writeText.mockRejectedValue(new DOMException('Document is not focused'))
        execCommand.mockReturnValue(true)

        await expect(copyToClipboard('data', 'table')).resolves.toBe(true)

        expect(infoSpy).toHaveBeenCalled()
        expect(errorSpy).not.toHaveBeenCalled()
    })

    it('reports failure when the fallback silently copies nothing', async () => {
        writeText.mockRejectedValue(new DOMException('Document is not focused'))
        execCommand.mockReturnValue(false)

        await expect(copyToClipboard('data', 'table')).resolves.toBe(false)

        expect(infoSpy).not.toHaveBeenCalled()
        expect(errorSpy).toHaveBeenCalledWith('Could not copy table to clipboard. Try again in a moment.')
        expect(captureSpy).toHaveBeenCalled()
    })

    it('reports failure when the fallback throws', async () => {
        writeText.mockRejectedValue(new DOMException('Write permission denied'))
        execCommand.mockImplementation(() => {
            throw new Error('execCommand blew up')
        })

        await expect(copyToClipboard('data', 'table')).resolves.toBe(false)

        expect(errorSpy).toHaveBeenCalled()
        expect(captureSpy).toHaveBeenCalled()
    })
})
