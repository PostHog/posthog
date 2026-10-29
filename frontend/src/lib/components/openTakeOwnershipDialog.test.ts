import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { LemonDialog, LemonDialogProps } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { isOwnerUnavailableError, openTakeOwnershipDialog } from './openTakeOwnershipDialog'

describe('openTakeOwnershipDialog', () => {
    let dialogProps: LemonDialogProps | null
    let captureSpy: jest.SpyInstance
    let errorSpy: jest.SpyInstance

    beforeEach(() => {
        dialogProps = null
        jest.spyOn(LemonDialog, 'open').mockImplementation((props) => {
            dialogProps = props
        })
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(jest.fn())
        errorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    async function confirmAndClose(): Promise<void> {
        await dialogProps?.primaryButton?.onClick?.({} as any)
        dialogProps?.onAfterClose?.()
    }

    it('recognizes only the owner_unavailable API error', () => {
        expect(isOwnerUnavailableError(new ApiError('refused', 400, undefined, { code: 'owner_unavailable' }))).toBe(
            true
        )
        expect(isOwnerUnavailableError(new ApiError('refused', 400, undefined, { code: 'invalid' }))).toBe(false)
        expect(isOwnerUnavailableError({ code: 'owner_unavailable' })).toBe(false)
    })

    it('resolves true and reports the takeover once the request succeeds', async () => {
        const takeOwnership = jest.fn().mockResolvedValue(undefined)
        const result = openTakeOwnershipDialog({ resourceLabel: 'alert', resourceId: 'alert-1', takeOwnership })

        await confirmAndClose()

        expect(await result).toBe(true)
        expect(takeOwnership).toHaveBeenCalledTimes(1)
        expect(captureSpy).toHaveBeenCalledWith('alert ownership taken', { alert_id: 'alert-1' })
    })

    it('resolves false and toasts the API detail when the request fails', async () => {
        const takeOwnership = jest
            .fn()
            .mockRejectedValue(new ApiError('refused', 400, undefined, { detail: 'No access to this insight.' }))
        const result = openTakeOwnershipDialog({ resourceLabel: 'subscription', resourceId: 7, takeOwnership })

        await confirmAndClose()

        expect(await result).toBe(false)
        expect(errorSpy).toHaveBeenCalledWith('No access to this insight.')
        expect(captureSpy).not.toHaveBeenCalled()
    })

    it('waits for an in-flight takeover before reporting a dismissal', async () => {
        let finishTakeover: () => void = () => {}
        const takeOwnership = jest.fn(
            () =>
                new Promise<void>((resolve) => {
                    finishTakeover = resolve
                })
        )
        const result = openTakeOwnershipDialog({ resourceLabel: 'alert', resourceId: 'alert-1', takeOwnership })

        const confirming = dialogProps?.primaryButton?.onClick?.({} as any)
        dialogProps?.onAfterClose?.()
        finishTakeover()
        await confirming

        expect(await result).toBe(true)
    })

    it('resolves false when the dialog is dismissed', async () => {
        const takeOwnership = jest.fn()
        const result = openTakeOwnershipDialog({ resourceLabel: 'subscription', resourceId: 7, takeOwnership })

        dialogProps?.onAfterClose?.()

        expect(await result).toBe(false)
        expect(takeOwnership).not.toHaveBeenCalled()
    })
})
