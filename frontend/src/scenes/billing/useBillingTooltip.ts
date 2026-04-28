import { useCallback, useRef } from 'react'
import { Root } from 'react-dom/client'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import {
    SharedDomRootConfig,
    createOwnedRender,
    createSharedDomRoot,
    ensureSharedDomRoot,
    resetSharedDomRoot,
} from 'lib/utils/sharedDomRoot'

const sharedBillingTooltip = createSharedDomRoot()

const sharedBillingTooltipConfig: SharedDomRootConfig = {
    elementId: 'BillingTooltipWrapper',
    setupElement: (element) => {
        element.className =
            'BillingTooltipWrapper hidden absolute z-10 p-2 bg-bg-light rounded shadow-md text-xs pointer-events-none border border-border'
    },
}

function ensureSharedBillingTooltip(ownerId: string): [Root, HTMLElement] {
    const [, element] = ensureSharedDomRoot(sharedBillingTooltip, sharedBillingTooltipConfig)
    sharedBillingTooltip.owner = ownerId
    return [createOwnedRender(sharedBillingTooltip, ownerId), element]
}

function hideSharedBillingTooltipIfOwner(ownerId: string): void {
    if (sharedBillingTooltip.owner !== ownerId || !sharedBillingTooltip.element) {
        return
    }
    sharedBillingTooltip.element.classList.add('hidden')
    sharedBillingTooltip.element.classList.remove('block')
}

function cleanupSharedBillingTooltipIfOwner(ownerId: string): void {
    if (sharedBillingTooltip.owner !== ownerId) {
        return
    }
    sharedBillingTooltip.owner = null
    if (sharedBillingTooltip.element) {
        sharedBillingTooltip.element.classList.add('hidden')
        sharedBillingTooltip.element.classList.remove('block')
    }
    sharedBillingTooltip.root?.render(null)
}

export function useBillingTooltip(): {
    ensureBillingTooltip: () => [Root, HTMLElement]
    hideBillingTooltip: () => void
} {
    const ownerIdRef = useRef<string | null>(null)
    if (ownerIdRef.current === null) {
        ownerIdRef.current = Math.random().toString(36).substring(2, 11)
    }
    const ownerId = ownerIdRef.current

    const ensureBillingTooltip = useCallback((): [Root, HTMLElement] => ensureSharedBillingTooltip(ownerId), [ownerId])
    const hideBillingTooltip = useCallback((): void => hideSharedBillingTooltipIfOwner(ownerId), [ownerId])

    useOnMountEffect(() => {
        return () => {
            cleanupSharedBillingTooltipIfOwner(ownerId)
        }
    })

    return { ensureBillingTooltip, hideBillingTooltip }
}

export function __resetSharedBillingTooltipForTests(): void {
    resetSharedDomRoot(sharedBillingTooltip)
}
