// PROTOTYPE, never merged: PostHog/michaelr-context#419. Rendered only by the prototype story, never by the app.
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import {
    MESSAGING_NAV_VARIANTS,
    MessagingNavVariant,
    messagingNavPrototypeLogic,
    switchMessagingNavVariant,
} from './messagingNavPrototypeLogic'

// Usage flags from the element pass on the ticket: flag and control only, never a number.
export const MESSAGING_NAV_VARIANT_LABELS: Record<MessagingNavVariant, string> = {
    A: 'A (In-scene sidebar)',
    B: 'B (Contextual pane)',
    C: 'C (Rail item)',
}

export const MESSAGING_NAV_VARIANT_FLAGS: Record<MessagingNavVariant, string> = {
    A: 'muscle memory: Broadcasts row, setup tabs',
    B: 'muscle memory: Broadcasts row, setup tabs',
    C: 'muscle memory: Broadcasts row, setup tabs · new rail item',
}

function step(current: MessagingNavVariant, by: number): MessagingNavVariant {
    const index = MESSAGING_NAV_VARIANTS.indexOf(current)
    const count = MESSAGING_NAV_VARIANTS.length
    return MESSAGING_NAV_VARIANTS[(index + by + count) % count]
}

function isEditable(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
    )
}

export function MessagingNavPrototypeSwitcher(): JSX.Element {
    const { variant } = useValues(messagingNavPrototypeLogic)
    const { location } = useValues(router)

    // Email & Messaging sits low in the Products pane, so bring the open row into view for whoever opens the link.
    useEffect(() => {
        let tries = 0
        const interval = window.setInterval(() => {
            const row = document.querySelector('.TodayShell__sidebar [aria-current="page"]')
            row?.scrollIntoView({ block: 'center' })
            if (row || ++tries > 20) {
                window.clearInterval(interval)
            }
        }, 300)
        return () => window.clearInterval(interval)
    }, [location.pathname, variant])

    useEffect(() => {
        const onKey = (event: KeyboardEvent): void => {
            if (isEditable(event.target) || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) {
                return
            }
            switchMessagingNavVariant(step(variant, event.key === 'ArrowLeft' ? -1 : 1))
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [variant])

    return (
        <div
            className="fixed bottom-4 left-1/2 z-[9999] flex -translate-x-1/2 items-center gap-1 rounded-full border-2 border-[#f54e00] bg-[#151515] px-1 py-1 text-white shadow-lg"
            data-attr="prototype-variant-switcher"
        >
            <button
                type="button"
                aria-label="Previous variant"
                className="flex size-7 items-center justify-center rounded-full hover:bg-white/15"
                onClick={() => switchMessagingNavVariant(step(variant, -1))}
            >
                <IconChevronLeft />
            </button>
            <span className="flex max-w-[70vw] flex-col px-2 text-center leading-tight">
                <span className="text-xs font-semibold">Prototype · {MESSAGING_NAV_VARIANT_LABELS[variant]}</span>
                <span className="text-[10px] text-white/70">{MESSAGING_NAV_VARIANT_FLAGS[variant]}</span>
            </span>
            <button
                type="button"
                aria-label="Next variant"
                className="flex size-7 items-center justify-center rounded-full hover:bg-white/15"
                onClick={() => switchMessagingNavVariant(step(variant, 1))}
            >
                <IconChevronRight />
            </button>
        </div>
    )
}
