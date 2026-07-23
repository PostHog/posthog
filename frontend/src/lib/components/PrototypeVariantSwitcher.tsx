/**
 * PROTOTYPE ONLY — floating variant switcher for throwaway UI prototypes.
 *
 * Renders nothing in production builds. Reads/writes the `?variant=` search param
 * (with a sessionStorage fallback, since some scenes rewrite the URL on state changes
 * and drop unknown params). Cycle with the on-screen arrows or ← / → keys.
 *
 * Delete together with the prototype it serves.
 */
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

export interface PrototypeVariantOption {
    key: string
    name: string
}

const PROTOTYPING_ENABLED = process.env.NODE_ENV !== 'production'

function storageKey(prototypeId: string): string {
    return `prototype-variant-${prototypeId}`
}

function storedVariant(prototypeId: string): string | null {
    try {
        return sessionStorage.getItem(storageKey(prototypeId))
    } catch {
        return null
    }
}

function setStoredVariant(prototypeId: string, variant: string | null): void {
    try {
        if (variant) {
            sessionStorage.setItem(storageKey(prototypeId), variant)
        } else {
            sessionStorage.removeItem(storageKey(prototypeId))
        }
    } catch {
        // sessionStorage unavailable — the URL param still works, just not across rewrites
    }
}

/** Currently selected variant key, or null for the unmodified page. Always null in production. */
export function usePrototypeVariant(prototypeId: string, variants: PrototypeVariantOption[]): string | null {
    const { searchParams } = useValues(router)
    const { replace } = useActions(router)

    const validKeys = variants.map((v) => v.key)
    const paramVariant = typeof searchParams.variant === 'string' ? searchParams.variant : null
    const stored = storedVariant(prototypeId)
    const current =
        paramVariant && validKeys.includes(paramVariant)
            ? paramVariant
            : stored && validKeys.includes(stored)
              ? stored
              : null

    // Scene logics (e.g. filter → URL sync) rewrite search params and drop `variant` — put it
    // back so the selection survives filtering, reloads, and link sharing.
    useEffect(() => {
        if (!PROTOTYPING_ENABLED) {
            return
        }
        setStoredVariant(prototypeId, current)
        if (current && paramVariant !== current) {
            replace(
                router.values.location.pathname,
                { ...router.values.searchParams, variant: current },
                router.values.hashParams
            )
        }
    })

    return PROTOTYPING_ENABLED ? current : null
}

export function PrototypeVariantSwitcher({
    prototypeId,
    variants,
}: {
    prototypeId: string
    variants: PrototypeVariantOption[]
}): JSX.Element | null {
    const current = usePrototypeVariant(prototypeId, variants)
    const { replace } = useActions(router)

    // null = the unmodified page, always first in the cycle
    const order: (string | null)[] = [null, ...variants.map((v) => v.key)]

    const setVariant = (variant: string | null): void => {
        setStoredVariant(prototypeId, variant)
        const nextParams = { ...router.values.searchParams }
        if (variant) {
            nextParams.variant = variant
        } else {
            delete nextParams.variant
        }
        replace(router.values.location.pathname, nextParams, router.values.hashParams)
    }

    const cycle = (delta: number): void => {
        const index = order.indexOf(current)
        setVariant(order[(index + delta + order.length) % order.length])
    }

    useEffect(() => {
        if (!PROTOTYPING_ENABLED) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
                return
            }
            if (event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented) {
                return
            }
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            cycle(event.key === 'ArrowLeft' ? -1 : 1)
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    })

    if (!PROTOTYPING_ENABLED) {
        return null
    }

    const label = current ? `${current} — ${variants.find((v) => v.key === current)?.name ?? ''}` : 'Current page'

    return (
        <div
            className="fixed bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded-full border border-primary bg-surface-primary px-2 py-1 shadow-lg"
            style={{ zIndex: 1200 }}
        >
            <LemonTag type="warning" size="small">
                PROTOTYPE
            </LemonTag>
            <LemonButton
                size="xsmall"
                icon={<IconChevronLeft />}
                onClick={() => cycle(-1)}
                tooltip="Previous variant (←)"
            />
            <span className="text-xs font-semibold whitespace-nowrap min-w-40 text-center select-none">{label}</span>
            <LemonButton size="xsmall" icon={<IconChevronRight />} onClick={() => cycle(1)} tooltip="Next variant (→)" />
        </div>
    )
}
