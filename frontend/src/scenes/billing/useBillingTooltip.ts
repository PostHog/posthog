import { useCallback, useRef } from 'react'
import { Root, createRoot } from 'react-dom/client'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

let sharedBillingTooltipElement: HTMLElement | null = null
let sharedBillingTooltipRoot: Root | null = null
let sharedBillingTooltipOwner: string | null = null

function ensureSharedBillingTooltip(ownerId: string): [Root, HTMLElement] {
    if (!sharedBillingTooltipElement || !sharedBillingTooltipRoot) {
        const element = document.createElement('div')
        element.id = 'BillingTooltipWrapper'
        element.className =
            'BillingTooltipWrapper hidden absolute z-10 p-2 bg-bg-light rounded shadow-md text-xs pointer-events-none border border-border'
        document.body.appendChild(element)
        sharedBillingTooltipElement = element
        sharedBillingTooltipRoot = createRoot(element)
    }
    sharedBillingTooltipOwner = ownerId
    return [sharedBillingTooltipRoot, sharedBillingTooltipElement]
}

function hideSharedBillingTooltipIfOwner(ownerId: string): void {
    if (sharedBillingTooltipOwner !== ownerId || !sharedBillingTooltipElement) {
        return
    }
    sharedBillingTooltipElement.classList.add('hidden')
    sharedBillingTooltipElement.classList.remove('block')
}

function cleanupSharedBillingTooltipIfOwner(ownerId: string): void {
    if (sharedBillingTooltipOwner !== ownerId) {
        return
    }
    sharedBillingTooltipOwner = null
    if (sharedBillingTooltipElement) {
        sharedBillingTooltipElement.classList.add('hidden')
        sharedBillingTooltipElement.classList.remove('block')
    }
    sharedBillingTooltipRoot?.render(null)
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
    sharedBillingTooltipRoot?.unmount()
    sharedBillingTooltipElement?.remove()
    sharedBillingTooltipElement = null
    sharedBillingTooltipRoot = null
    sharedBillingTooltipOwner = null
}
