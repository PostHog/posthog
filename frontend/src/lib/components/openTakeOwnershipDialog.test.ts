import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { LemonDialog, LemonDialogProps } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { openTakeOwnershipDialog, ownerUnavailableCause } from './openTakeOwnershipDialog'

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

    it.each([
        ['owner_left_organization', 'left'],
        ['owner_lost_access', 'lost_access'],
        ['invalid', null],
    ])('reads the cause from the %s API error code', (code, cause) => {
        expect(ownerUnavailableCause(new ApiError('refused', 400, undefined, { code }))).toBe(cause)
    })

    it('ignores an owner code that is not an API error', () => {
        expect(ownerUnavailableCause({ code: 'owner_left_organization' })).toBe(null)
    })

    it('resolves true and reports the takeover once the request succeeds', async () => {
        const takeOwnership = jest.fn().mockResolvedValue(undefined)
        const result = openTakeOwnershipDialog({
            resourceLabel: 'alert',
            resourceId: 'alert-1',
            owner: null,
            cause: 'left',
            takeOwnership,
        })

        await confirmAndClose()

        expect(await result).toBe(true)
        expect(takeOwnership).toHaveBeenCalledTimes(1)
        expect(captureSpy).toHaveBeenCalledWith('alert ownership taken', { alert_id: 'alert-1' })
    })

    it('resolves false and toasts the API detail when the request fails', async () => {
        const takeOwnership = jest
            .fn()
            .mockRejectedValue(new ApiError('refused', 400, undefined, { detail: 'No access to this insight.' }))
        const result = openTakeOwnershipDialog({
            resourceLabel: 'subscription',
            resourceId: 7,
            owner: null,
            cause: 'left',
            takeOwnership,
        })

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
        const result = openTakeOwnershipDialog({
            resourceLabel: 'alert',
            resourceId: 'alert-1',
            owner: null,
            cause: 'left',
            takeOwnership,
        })

        const confirming = dialogProps?.primaryButton?.onClick?.({} as any)
        dialogProps?.onAfterClose?.()
        finishTakeover()
        await confirming

        expect(await result).toBe(true)
    })

    it('resolves false when the dialog is dismissed', async () => {
        const takeOwnership = jest.fn()
        const result = openTakeOwnershipDialog({
            resourceLabel: 'subscription',
            resourceId: 7,
            owner: null,
            cause: 'left',
            takeOwnership,
        })

        dialogProps?.onAfterClose?.()

        expect(await result).toBe(false)
        expect(takeOwnership).not.toHaveBeenCalled()
    })
})
