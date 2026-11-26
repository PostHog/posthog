// PROTOTYPE, throwaway: the floating variant switcher. Shown only in builds made with POSTHOG_PROTOTYPE=1.
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    MESSAGING_CTA_TODAY_HINTS,
    MESSAGING_CTA_VARIANTS_BY_AREA,
    MESSAGING_CTA_VARIANT_HINTS,
    MESSAGING_CTA_VARIANT_LABELS,
    type MessagingCtaArea,
    currentMessagingCtaVariant,
    rememberVariantFromUrl,
    setMessagingCtaVariant,
} from './messagingCtaPrototype'

function isTyping(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) {
        return false
    }
    return (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable ||
        !!target.closest('[contenteditable="true"]')
    )
}

export function MessagingCtaPrototypeSwitcher({ area }: { area: MessagingCtaArea }): JSX.Element | null {
    const { searchParams } = useValues(router)
    const variants = MESSAGING_CTA_VARIANTS_BY_AREA[area]
    const stored = currentMessagingCtaVariant(searchParams)
    const current = variants.includes(stored) ? stored : 'today'
    const index = variants.indexOf(current)
    const count = variants.length
    const previous = variants[(index - 1 + count) % count]
    const next = variants[(index + 1) % count]
    const hint = current === 'today' ? MESSAGING_CTA_TODAY_HINTS[area] : MESSAGING_CTA_VARIANT_HINTS[current]

    useEffect(() => rememberVariantFromUrl(searchParams), [searchParams])

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (isTyping(event.target) || event.metaKey || event.ctrlKey || event.altKey) {
                return
            }
            if (event.key === 'ArrowLeft') {
                setMessagingCtaVariant(previous)
            } else if (event.key === 'ArrowRight') {
                setMessagingCtaVariant(next)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [previous, next])

    if (!process.env.POSTHOG_PROTOTYPE) {
        return null
    }

    return (
        <div
            className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-2 rounded-full border-2 border-warning bg-black text-white px-2 py-1 shadow-lg"
            data-attr="prototype-variant-switcher"
        >
            <LemonButton
                size="small"
                icon={<IconChevronLeft className="text-white" />}
                onClick={() => setMessagingCtaVariant(previous)}
                tooltip={`Previous: ${MESSAGING_CTA_VARIANT_LABELS[previous]}`}
                data-attr="prototype-variant-previous"
            />
            <div className="flex flex-col items-center px-2 min-w-80">
                <span className="text-sm font-semibold" data-attr="prototype-variant-label">
                    {MESSAGING_CTA_VARIANT_LABELS[current]}
                </span>
                <span className="text-xs opacity-75">{hint}</span>
            </div>
            <LemonButton
                size="small"
                icon={<IconChevronRight className="text-white" />}
                onClick={() => setMessagingCtaVariant(next)}
                tooltip={`Next: ${MESSAGING_CTA_VARIANT_LABELS[next]}`}
                data-attr="prototype-variant-next"
            />
        </div>
    )
}
